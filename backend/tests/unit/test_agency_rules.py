"""Agency rules without a database (Phase 14): the lower role, and "via agency" scoping."""

from __future__ import annotations

import uuid

from app.core.delegation import set_via_agency, via_agency
from app.domains.agency.access import lower


def test_the_lower_role_wins():
    assert lower("owner", "manager") == "manager"
    assert lower("analyst", "manager") == "analyst"
    assert lower("viewer", "viewer") == "viewer"


def test_via_agency_applies_only_to_the_client():
    client, agency, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    set_via_agency(client, agency)
    assert via_agency(client) == agency
    assert via_agency(other) is None
    assert via_agency(None) is None
    set_via_agency(client, None)
    assert via_agency(client) is None
