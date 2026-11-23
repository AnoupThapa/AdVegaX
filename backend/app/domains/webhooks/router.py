"""Platform webhook endpoint (task 2A-05). Public: no session and no CSRF token — the platform's
signature over the raw body is the authentication (PHASE_02A_PLAN §7, §11)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import MetaDep, RuntimeDep
from app.api.responses import Envelope, ok
from app.domains.webhooks.service import receive

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/{provider}", include_in_schema=False)
async def platform_webhook(
    provider: str, request: Request, rt: RuntimeDep, meta: MetaDep
) -> Envelope[dict[str, str]]:
    """One URL per platform for every topic, including Shopify's privacy topics. Answers
    quickly: verification and a small insert only; any follow-up work is a background job."""
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    outcome = await run_in_threadpool(receive, rt, provider, headers, body, ip=meta.ip)
    return ok({"status": outcome.value})
