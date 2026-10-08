"""Audit refused actions in their own transaction (1A follow-up, A16).

A denial aborts the business transaction, so the audit record is written separately and
best-effort: a failure to audit never turns a 403 into a 500.
"""

from __future__ import annotations

import logging

from app.domains.audit.service import Actor, record_audit
from app.domains.organizations.permissions import AuthorizationDenied
from app.runtime import Runtime

logger = logging.getLogger("advegax.audit")


def audit_denial(rt: Runtime, denial: AuthorizationDenied) -> None:
    ctx = denial.ctx
    try:
        with rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="authorization.denied",
                resource_type=denial.resource_type or "permission",
                resource_id=denial.resource_id,
                result="denied",
                metadata={"permission": denial.permission.value, "role": ctx.role},
            )
    except Exception:
        logger.exception("denial_audit_failed")
