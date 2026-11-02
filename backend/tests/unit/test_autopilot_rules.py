"""Autopilot's ceilings, settings and emails (Phase 12, 12-02 … 12-04)."""

from __future__ import annotations

import uuid

from app.core.settings import Settings
from app.domains.autopilot.schemas import AutopilotLimits
from app.domains.autopilot.service import ceilings, looser
from app.domains.notifications.templates import render


def test_limits_may_only_be_stricter_than_the_installation():
    bound = ceilings(Settings())
    same = AutopilotLimits(**bound.model_dump())
    assert looser(same, bound) == []
    loose = same.model_copy(
        update={"max_changes_per_day": 6, "campaign_cooldown_days": 1, "cumulative_window_days": 7}
    )
    assert looser(loose, bound) == [
        "max_changes_per_day",
        "campaign_cooldown_days",
        "cumulative_window_days",
    ]


def test_the_rollout_list_is_read_from_a_comma_list(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("AUTOPILOT_ORGANIZATIONS", f"{a}, {b}")
    assert Settings().AUTOPILOT_ORGANIZATIONS == [a, b]
    assert Settings().AUTOPILOT_ENABLED is False  # off by default


def test_the_emails_name_each_change_and_the_reason():
    subject, text, html = render(
        "autopilot_changes",
        {
            "organization_name": "Eve <Zone>",
            "lines": [
                "Paused Gloves",
                "Lowered the daily budget of Mask from AUD 50.00 to AUD 40.00",
            ],
            "link": "https://app.example/orgs/1/changes",
        },
    )
    assert subject == "AdVegaX autopilot made changes for Eve <Zone>"
    assert "- Paused Gloves\n" in text and "Eve &lt;Zone&gt;" in html
    subject, text, _ = render(
        "autopilot_stopped",
        {
            "organization_name": "Eve",
            "reason": "An automatic change could not be made.",
            "link": "x",
        },
    )
    assert "stopped" in subject and "could not be made" in text
