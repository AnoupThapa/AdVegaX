"""The creative engine API (task 9-05, PLAN §7, Q-9-2 … Q-9-10) against the AI simulator.

The golden shop of ``test_strategy_context`` (one AUD product, "Nitrile gloves", priced 50.00)
with a strategy for Google Ads and Meta, marked ready.
"""

from __future__ import annotations

import copy
import io
import uuid

import pytest
from app.core.storage import LocalStorage
from PIL import Image
from sqlalchemy import text

from tests.api.test_strategies_api import _generate, owner  # noqa: F401  (fixture)
from tests.api.test_strategy_context import shop  # noqa: F401  (fixture)

GOOGLE = {
    "angle": "Bulk savings",
    "rationale": "Buyers search for bulk boxes.",
    "compliance_notes": ["Check the delivery promise."],
    "headlines": ["Nitrile Gloves in Bulk", "Boxes of 100 for $50.00", "Fast Australian Delivery"],
    "descriptions": [
        "Powder-free nitrile gloves for clinics, kitchens and cleaners.",
        "Order online today for delivery across Australia.",
    ],
    "path1": "gloves",
    "path2": "nitrile",
}
META = {
    "angle": "Busy kitchens",
    "rationale": "Hospitality owners reorder monthly.",
    "compliance_notes": [],
    "primary_texts": ["Reliable nitrile gloves for busy kitchens and clinics."],
    "headlines": ["Bulk nitrile gloves"],
    "descriptions": ["Free delivery"],
    "call_to_action": "SHOP_NOW",
}
ANSWER = {"google_ads": [GOOGLE], "meta_ads": [META]}


@pytest.fixture
def maker(owner, tmp_path, runtime):  # noqa: F811
    strategy = _generate(owner)
    assert owner.post(f"{owner.base}/{strategy['id']}/ready").status_code == 200
    owner.strategy = strategy["id"]
    owner.store = LocalStorage(tmp_path)
    runtime.extras["storage"] = owner.store
    owner.sets = f"/organizations/{owner.org}/ai/creative-sets"
    owner.creatives = f"/organizations/{owner.org}/creatives"
    owner.assets = f"/organizations/{owner.org}/creative-assets"
    return owner


def _draft(maker, answer=ANSWER):
    maker.sim.queue(answer)
    response = maker.post(maker.sets, {"strategy_id": maker.strategy})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _one(data, platform):
    return next(c for c in data["creatives"] if c["platform"] == platform)


def _png(size=(800, 800), noise=False) -> bytes:
    out = io.BytesIO()
    image = (
        Image.effect_noise(size, 80).convert("RGB")
        if noise
        else Image.new("RGB", size, (10, 120, 200))
    )
    image.save(out, format="PNG")
    return out.getvalue()


def _audit(admin_engine, org):
    with admin_engine.connect() as db:
        return [
            (r.action, r.after_json, r.metadata_json)
            for r in db.execute(
                text(
                    "SELECT action, after_json, metadata AS metadata_json FROM audit_logs WHERE "
                    "organization_id = :o AND resource_type LIKE 'creative%' ORDER BY created_at"
                ),
                {"o": org},
            )
        ]


# ------------------------------------------------------------------ drafting
def test_drafts_come_from_a_ready_strategy_within_the_limits(maker, admin_engine):
    data = _draft(maker)
    assert data["strategy_id"] == maker.strategy
    assert data["product_title"] == "Nitrile gloves"
    google, meta = _one(data, "google_ads"), _one(data, "meta_ads")
    assert (google["format"], google["status"], google["version"]) == ("google_rsa", "draft", 1)
    assert google["content"]["headlines"] == GOOGLE["headlines"]
    assert google["checks"] == [] and google["approvable"] is True
    assert (meta["format"], meta["content"]["call_to_action"]) == ("meta_single", "SHOP_NOW")
    assert google["compliance_notes"] == ["Check the delivery promise."]
    prompt = maker.sim.bodies()[-1]["messages"][0]["content"]
    assert '"catalogue_prices": [\n  "50.00"' in prompt
    assert prompt.count("</brief>") == 1 and prompt.count("</store_text>") == 1
    assert "40.00" not in prompt.split("<brief>")[1].split("</brief>")[0]  # no budget amounts
    with admin_engine.connect() as db:
        task = db.execute(
            text("SELECT task FROM ai_runs WHERE id = :i"), {"i": data["ai_run_id"]}
        ).scalar_one()
    assert task == "creative_copy"
    (action, after, _), *_ = _audit(admin_engine, maker.org)
    assert (action, after["concepts"]) == ("creative_set.generated", 2)
    sets = maker.get(f"/organizations/{maker.org}/creative-sets?strategy_id={maker.strategy}")
    assert sets.json()["data"][0]["concepts"] == 2


def test_only_a_ready_strategy_makes_creatives(maker):
    draft = _generate(maker)
    maker.sim.queue(ANSWER)
    response = maker.post(maker.sets, {"strategy_id": draft["id"]})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "STRATEGY_NOT_READY")
    assert maker.post(maker.sets, {"strategy_id": str(uuid.uuid4())}).status_code == 404


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda a: a["google_ads"][0]["headlines"].__setitem__(0, "x" * 31),
            "google_ads[0].too_long:headlines[0]=30",
        ),
        (
            lambda a: a["google_ads"][0]["headlines"].__setitem__(0, "Call 02 9876 5432"),
            "google_ads[0].phone_number:headlines[0]",
        ),
        (
            lambda a: a["meta_ads"][0]["primary_texts"].__setitem__(
                0, "Gloves that cure dermatitis."
            ),
            "meta_ads[0].prohibited_term:primary_texts[0]=cure",
        ),
        (
            lambda a: a["google_ads"][0]["headlines"].__setitem__(1, "Now only $39.95"),
            "google_ads[0].price_not_in_catalogue:headlines[1]=39.95",
        ),
        (lambda a: a.pop("meta_ads"), "shape:answer"),
        (lambda a: a["meta_ads"][0].update(budget=500), "meta_ads[0].shape:content"),
    ],
)
def test_answers_that_break_the_rules_are_never_kept(maker, change, reason):
    bad = copy.deepcopy(ANSWER)
    change(bad)
    maker.sim.queue(bad, bad)
    response = maker.post(maker.sets, {"strategy_id": maker.strategy})
    assert response.json()["error"]["code"] == "AI_ANSWER_REJECTED"
    assert {"reason": reason} in response.json()["error"]["details"]
    assert maker.get(f"/organizations/{maker.org}/creative-sets").json()["data"] == []


# ------------------------------------------------------------------ versions and approval
def test_an_edit_makes_a_new_version_and_keeps_the_old(maker, admin_engine):
    google = _one(_draft(maker), "google_ads")
    edited = {
        **google["content"],
        "headlines": ["Gloves for Clinics", *google["content"]["headlines"][1:]],
    }
    response = maker.patch(f"{maker.creatives}/{google['id']}", {"content": edited})
    assert response.status_code == 200, response.text
    v2 = response.json()["data"]
    assert (v2["version"], v2["status"], v2["latest"]) == (2, "draft", True)
    assert [v["version"] for v in v2["versions"]] == [1, 2]
    v1 = maker.get(f"{maker.creatives}/{google['id']}").json()["data"]
    assert (v1["content"], v1["latest"]) == (google["content"], False)
    stale = maker.patch(f"{maker.creatives}/{google['id']}", {"content": edited})
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "CREATIVE_NOT_EDITABLE")
    bad = maker.patch(f"{maker.creatives}/{v2['id']}", {"content": {"headlines": []}})
    assert bad.status_code == 422


def test_approval_needs_every_check_to_pass(maker, admin_engine):
    meta = _one(_draft(maker), "meta_ads")
    claim = {**meta["content"], "primary_texts": ["Kills viruses on contact."]}
    v2 = maker.patch(f"{maker.creatives}/{meta['id']}", {"content": claim}).json()["data"]
    assert v2["approvable"] is False
    assert v2["checks"][0]["code"] == "prohibited_term"
    refused = maker.post(f"{maker.creatives}/{v2['id']}/approve", {})
    assert refused.json()["error"]["code"] == "CREATIVE_CHECKS_FAILED"
    assert refused.json()["error"]["details"][0]["reason"] == "prohibited_term"
    fixed = {**meta["content"], "primary_texts": ["Strong nitrile gloves for daily use."]}
    v3 = maker.patch(f"{maker.creatives}/{v2['id']}", {"content": fixed}).json()["data"]
    approved = maker.post(f"{maker.creatives}/{v3['id']}/approve", {}).json()["data"]
    assert (approved["status"], approved["version"]) == ("approved", 3)
    assert approved["decided_by"] is not None
    actions = [a for a, *_ in _audit(admin_engine, maker.org)]
    assert actions[-1] == "creative.approved"
    assert all("Kills viruses" not in str(r) for r in _audit(admin_engine, maker.org))


def test_flagged_wording_needs_a_confirmation(maker, admin_engine):
    meta = _one(_draft(maker), "meta_ads")
    best = {**meta["content"], "headlines": ["The best bulk gloves"]}
    v2 = maker.patch(f"{maker.creatives}/{meta['id']}", {"content": best}).json()["data"]
    assert v2["approvable"] is True and v2["checks"][0]["severity"] == "flag"
    first = maker.post(f"{maker.creatives}/{v2['id']}/approve", {})
    assert first.json()["error"]["details"][0] | {} == {
        "reason": "superlative",
        "field": "headlines[0]",
        "detail": "best",
        "severity": "flag",
    }
    ok = maker.post(f"{maker.creatives}/{v2['id']}/approve", {"confirm_flags": True})
    assert ok.json()["data"]["status"] == "approved"
    *_, (action, _, metadata) = _audit(admin_engine, maker.org)
    assert (action, metadata["flags_confirmed"]) == ("creative.approved", ["best"])


def test_one_approved_version_per_concept(maker):
    google = _one(_draft(maker), "google_ads")
    maker.post(f"{maker.creatives}/{google['id']}/approve", {})
    edited = {**google["content"], "path2": "bulk"}
    v2 = maker.patch(f"{maker.creatives}/{google['id']}", {"content": edited}).json()["data"]
    assert maker.get(f"{maker.creatives}/{google['id']}").json()["data"]["status"] == "approved"
    maker.post(f"{maker.creatives}/{v2['id']}/approve", {})
    assert maker.get(f"{maker.creatives}/{google['id']}").json()["data"]["status"] == "archived"
    approved = maker.get(f"{maker.creatives}?status=approved").json()["data"]
    assert [c["id"] for c in approved] == [v2["id"]]  # what the campaign builder may use


def test_reject_needs_a_reason_and_is_final_for_that_version(maker):
    meta = _one(_draft(maker), "meta_ads")
    assert maker.post(f"{maker.creatives}/{meta['id']}/reject", {"reason": ""}).status_code == 422
    rejected = maker.post(f"{maker.creatives}/{meta['id']}/reject", {"reason": "Too generic."})
    assert rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["data"]["decision_reason"] == "Too generic."
    again = maker.post(f"{maker.creatives}/{meta['id']}/approve", {})
    assert again.json()["error"]["code"] == "CREATIVE_NOT_EDITABLE"
    v2 = maker.patch(f"{maker.creatives}/{meta['id']}", {"content": meta["content"]})
    assert v2.json()["data"]["status"] == "draft"  # a new version can be tried
    archived = maker.post(f"{maker.creatives}/{v2.json()['data']['id']}/archive")
    assert archived.json()["data"]["status"] == "archived"
    assert maker.patch(f"{maker.creatives}/{v2.json()['data']['id']}", {}).status_code == 409


def test_roles(maker, make_client):
    data = _draft(maker)
    google = _one(data, "google_ads")
    analyst, manager, viewer = make_client(), make_client(), make_client()
    for client, role in ((analyst, "analyst"), (manager, "manager"), (viewer, "viewer")):
        email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
        client.signup(email)
        maker.invite_and_join(maker.org, client, email, role)
    one = f"{maker.creatives}/{google['id']}"
    assert viewer.get(one).status_code == 200
    assert viewer.patch(one, {"content": google["content"]}).status_code == 403
    v2 = analyst.patch(one, {"content": google["content"]})
    assert v2.status_code == 200
    v2_id = v2.json()["data"]["id"]
    assert analyst.post(f"{maker.creatives}/{v2_id}/approve", {}).status_code == 403
    assert analyst.post(f"{maker.creatives}/{v2_id}/reject", {"reason": "nope"}).status_code == 403
    assert manager.post(f"{maker.creatives}/{v2_id}/approve", {}).status_code == 200
    assert viewer.post(maker.sets, {"strategy_id": maker.strategy}).status_code == 403
    rules = f"/organizations/{maker.org}/creative-rules"
    assert manager.put(rules, {"prohibited_terms": [], "allowed_caps": []}).status_code == 403
    assert viewer.get(rules).status_code == 200


def test_the_organizations_rules(maker):
    rules = f"/organizations/{maker.org}/creative-rules"
    base = maker.get(rules).json()["data"]
    assert base["prohibited_terms"] == [] and "cure" in base["base_prohibited_terms"]
    saved = maker.put(rules, {"prohibited_terms": ["  Hospital  Grade "], "allowed_caps": ["eve"]})
    assert saved.json()["data"]["prohibited_terms"] == ["hospital grade"]
    assert saved.json()["data"]["allowed_caps"] == ["EVE"]
    assert (
        maker.put(rules, {"prohibited_terms": ["<script>"], "allowed_caps": []}).status_code == 422
    )
    meta = _one(_draft(maker), "meta_ads")
    texts = {**meta["content"], "primary_texts": ["Hospital grade gloves from EVE Zone."]}
    v2 = maker.patch(f"{maker.creatives}/{meta['id']}", {"content": texts}).json()["data"]
    assert [c["code"] for c in v2["checks"]] == ["prohibited_term"]  # EVE is allowed


# ------------------------------------------------------------------ images
def test_an_image_is_cleaned_stored_privately_and_attached(maker, make_client):
    response = maker.upload(maker.assets, "../../evil name.png", _png())
    assert response.status_code == 201, response.text
    asset = response.json()["data"]
    assert (asset["content_type"], asset["width"], asset["height"]) == ("image/png", 800, 800)
    assert asset["original_name"] == "../../evil name.png"  # shown only
    content = maker.get(f"{maker.assets}/{asset['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert Image.open(io.BytesIO(content.content)).size == (800, 800)
    meta = _one(_draft(maker), "meta_ads")
    v2 = maker.patch(f"{maker.creatives}/{meta['id']}", {"asset_id": asset["id"]}).json()["data"]
    assert v2["asset"]["id"] == asset["id"]
    google = _one(
        maker.get(f"/organizations/{maker.org}/creative-sets/{v2['set_id']}").json()["data"],
        "google_ads",
    )
    wrong = maker.patch(f"{maker.creatives}/{google['id']}", {"asset_id": asset["id"]})
    assert wrong.json()["error"]["details"] == [{"field": "asset_id", "issue": "meta_only"}]
    maker.post(f"{maker.assets}/{asset['id']}/archive")
    assert maker.get(maker.assets).json()["data"] == []
    other = _one(
        maker.get(f"/organizations/{maker.org}/creative-sets/{v2['set_id']}").json()["data"],
        "meta_ads",
    )
    assert other["asset"]["id"] == asset["id"]  # archiving keeps what is already attached
    outsider = make_client()
    outsider.signup(f"peek-{uuid.uuid4().hex[:6]}@example.com")
    org = outsider.create_org("Peek Co")["id"]
    assert (
        outsider.get(f"/organizations/{org}/creative-assets/{asset['id']}/content").status_code
        == 404
    )
    assert outsider.get(f"{maker.assets}/{asset['id']}/content").status_code in (403, 404)


@pytest.mark.parametrize(
    ("name", "data", "kind", "reason"),
    [
        ("evil.png", b"#!/bin/sh\necho owned\n", "image/png", "not_an_image"),
        ("small.png", None, "image/png", "too_small"),
        ("anim.gif", b"GIF89a" + b"\x00" * 64, "image/gif", "not_an_image"),
    ],
)
def test_what_is_not_an_acceptable_image(maker, name, data, kind, reason):
    payload = _png((300, 300)) if data is None else data
    response = maker.upload(maker.assets, name, payload, kind)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "ASSET_INVALID")
    assert response.json()["error"]["details"] == [{"reason": reason}]


def test_upload_size_limits(maker, runtime):
    runtime.settings = runtime.settings.model_copy(update={"ASSET_MAX_BYTES": 5000})
    response = maker.upload(maker.assets, "big.png", _png(noise=True))
    assert response.json()["error"]["details"] == [{"reason": "too_large"}]
    huge = maker.upload(maker.assets, "huge.png", b"x" * 200_000)
    assert huge.status_code in (413, 422)


def test_multipart_is_only_accepted_for_uploads(maker):
    response = maker.http.post(
        f"/api/v1/organizations/{maker.org}/creative-rules",
        files={"file": ("a.png", _png(), "image/png")},
        headers=maker._headers(None),
    )
    assert response.status_code in (405, 415)
    json_upload = maker.post(maker.assets, {"file": "x"})
    assert json_upload.status_code == 415


def test_outsiders_see_no_creatives(maker, make_client):
    data = _draft(maker)
    outsider = make_client()
    outsider.signup(f"out-{uuid.uuid4().hex[:6]}@example.com")
    org = outsider.create_org("Out Co")["id"]
    google = _one(data, "google_ads")
    assert outsider.get(f"/organizations/{org}/creatives/{google['id']}").status_code == 404
    assert outsider.get(f"/organizations/{org}/creative-sets/{data['id']}").status_code == 404
    assert (
        outsider.post(f"/organizations/{org}/creatives/{google['id']}/approve", {}).status_code
        == 404
    )
    assert outsider.get(f"/organizations/{org}/creatives").json()["data"] == []
