"""Permission matrix, role assignment rules, logging scrubber, templates, helpers."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.core.correlation import sanitize_request_id, set_correlation_id
from app.core.errors import Forbidden, NotFound
from app.core.logging import REDACTED, JsonFormatter, scrub
from app.domains.notifications.service import NotificationService, humanize
from app.domains.notifications.templates import TEMPLATES, render
from app.domains.organizations.permissions import (
    PERMISSION_MATRIX,
    Permission,
    Role,
    authorize,
    can_assign,
    has_permission,
)
from app.domains.organizations.service import slugify
from app.domains.organizations.tenancy import TenantContext

ORG = uuid.uuid4()


def ctx(role: str) -> TenantContext:
    return TenantContext(organization_id=ORG, user_id=uuid.uuid4(), role=role)


def test_matrix_matches_api_spec():
    assert PERMISSION_MATRIX[Permission.AUDIT_VIEW] == {Role.OWNER, Role.ADMIN}
    assert PERMISSION_MATRIX[Permission.MEMBERS_MANAGE] == {Role.OWNER, Role.ADMIN}
    assert PERMISSION_MATRIX[Permission.ORG_VIEW] == set(Role)
    # Phase 8 (Q-8-7, Q-8-8): everyone reads strategies; viewers cannot generate or change them;
    # AI usage is for owners and admins.
    assert PERMISSION_MATRIX[Permission.STRATEGIES_VIEW] == set(Role)
    assert PERMISSION_MATRIX[Permission.STRATEGIES_MANAGE] == set(Role) - {Role.VIEWER}
    assert PERMISSION_MATRIX[Permission.AI_USAGE_VIEW] == {Role.OWNER, Role.ADMIN}
    # Phase 9 (Q-9-6): drafting for all but viewers; approving for owner, admin and manager.
    assert PERMISSION_MATRIX[Permission.CREATIVES_VIEW] == set(Role)
    assert PERMISSION_MATRIX[Permission.CREATIVES_MANAGE] == set(Role) - {Role.VIEWER}
    assert PERMISSION_MATRIX[Permission.CREATIVES_APPROVE] == {Role.OWNER, Role.ADMIN, Role.MANAGER}
    assert not has_permission("unknown-role", Permission.ORG_VIEW)


@pytest.mark.parametrize("role", list(Role))
def test_authorize_by_role(role):
    authorize(ctx(role), Permission.ORG_VIEW)
    if role in (Role.OWNER, Role.ADMIN):
        authorize(ctx(role), Permission.MEMBERS_MANAGE)
    else:
        with pytest.raises(Forbidden):
            authorize(ctx(role), Permission.MEMBERS_MANAGE)


def test_authorize_rejects_foreign_resource_as_not_found():
    foreign = SimpleNamespace(organization_id=uuid.uuid4())
    with pytest.raises(NotFound):
        authorize(ctx(Role.OWNER), Permission.ORG_VIEW, foreign)
    authorize(ctx(Role.OWNER), Permission.ORG_VIEW, SimpleNamespace(organization_id=ORG))


def test_can_assign():
    assert can_assign(Role.OWNER, Role.OWNER)
    assert not can_assign(Role.ADMIN, Role.OWNER)
    assert can_assign(Role.ADMIN, Role.ADMIN)
    assert can_assign(Role.ADMIN, Role.VIEWER)
    assert not can_assign(Role.MANAGER, Role.ADMIN)


def test_scrub_and_json_logging(caplog):
    data = {
        "password": "p",
        "nested": {"session_token": "t", "ok": 1},
        "items": [{"csrf": "x"}],
        "Authorization": "Bearer y",
    }
    cleaned = scrub(data)
    assert cleaned["password"] == REDACTED
    assert cleaned["nested"] == {"session_token": REDACTED, "ok": 1}
    assert cleaned["items"] == [{"csrf": REDACTED}]
    assert cleaned["Authorization"] == REDACTED
    set_correlation_id("req-12345678")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    record.secret_key = "should-not-appear"  # type: ignore[attr-defined]
    record.user_id = "u1"  # type: ignore[attr-defined]
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "hello"
    assert line["correlation_id"] == "req-12345678"
    assert line["secret_key"] == REDACTED
    assert line["user_id"] == "u1"
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    assert "ValueError" in json.loads(JsonFormatter().format(record))["exception"]
    set_correlation_id(None)


def test_request_id_sanitization():
    assert sanitize_request_id("abcdef12") == "abcdef12"
    assert sanitize_request_id("x") != "x"
    assert sanitize_request_id(None)
    assert sanitize_request_id("a" * 65) != "a" * 65


def test_templates_render_and_escape():
    for name in TEMPLATES:
        keys = (
            "name",
            "link",
            "expires_in",
            "sign_in_link",
            "reset_link",
            "organization_name",
            "role",
            "inviter_name",
            "message",
            "reason",
        )
        variables = {**dict.fromkeys(keys, "<b>&</b>"), "lines": ["<b>&</b>"]}
        subject, text, html = render(name, variables)
        assert "\n" not in subject
        assert "<b>&</b>" in text or name in ("password_reset",)
        assert "<b>&</b>" not in html
    with pytest.raises(Exception):  # noqa: B017 - StrictUndefined
        render("password_reset", {})


def test_humanize():
    assert humanize(timedelta(hours=24)) == "24 hours"
    assert humanize(timedelta(days=7)) == "7 days"
    assert humanize(timedelta(minutes=30)) == "30 minutes"
    assert humanize(timedelta(hours=1)) == "1 hour"
    assert humanize(timedelta(seconds=90)) == "1 minute"


def test_unknown_template_rejected():
    with pytest.raises(ValueError, match="Unknown email template"):
        NotificationService(lambda _: None).send_email(
            None,
            template="nope",  # type: ignore[arg-type]
            recipient="a@example.com",
            variables={},
        )


def test_slugify():
    assert slugify("Eve Zone — Wholesale!") == "eve-zone-wholesale"
    assert slugify("!") == "org"
    assert len(slugify("x" * 200)) <= 50
