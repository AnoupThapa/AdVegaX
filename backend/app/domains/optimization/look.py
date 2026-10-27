"""The daily look and the advice's life (Phase 11, task 11-05, PHASE_11_PLAN Q-11-5 … Q-11-9;
A30).

**Once a day per organization** (after ``OPTIMIZATION_RUN_HOUR`` in its reporting time zone,
started by the scheduler) and on **"Look again now"**:

1. AdVegaX's own figures (Phase 6) for every campaign of the linked ad accounts over the recent
   and the baseline days, the business's gross margin, and Phase 7's funnel findings;
2. the five rules (``signals``), then a proposal with pre-checks for each (``candidates``);
3. advice **rejected** in the quiet period is not shown again unless the loss at least doubled;
   advice **approved** in the last days is not shown again; a campaign with an open change gets
   none;
4. the AI explains and ranks (``explain``), or AdVegaX's own words ("Rules only");
5. the open advice of the previous look is **superseded** and the new advice kept, valid for
   ``OPTIMIZATION_VALID_FOR``.

The same run records **outcomes**: 7 and 14 days after a change made from advice, the
campaign's figures over that many days before and after it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AiAnswerRejected, AiLimitReached, AiUnavailableError
from app.core.settings import Settings
from app.domains.actions.models import Action
from app.domains.ai.runs import run_task
from app.domains.audit.service import Actor, record_audit
from app.domains.funnel.engine import load_funnel
from app.domains.funnel.findings import find_drop_offs, rules_from
from app.domains.fx.service import FxTable
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.domains.metrics.campaigns import campaigns, products
from app.domains.metrics.engine import Figure, Scope, load_inputs, load_scope
from app.domains.optimization.candidates import Candidate, candidate_for
from app.domains.optimization.explain import Item, item_of, optimizer_task, rules_text
from app.domains.optimization.models import (
    OptimizationSettings,
    Recommendation,
    RecommendationOutcome,
)
from app.domains.optimization.signals import (
    CampaignInput,
    Margin,
    Signal,
    Thresholds,
    evaluate,
    funnel_signals,
    margin_of,
)
from app.domains.organizations.models import Organization
from app.runtime import Runtime

logger = logging.getLogger("advegax.optimization")

JOB_LOOK = "optimization.look"
OUTCOME_KEYS = ("spend", "conversions", "cost_per_conversion", "conversion_value")
WORSE = Decimal(2)  # a rejected loss shows again once it at least doubled (Q-11-8)


def _shift(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)


def settings_for(rt: Runtime, session: Session, org_id: uuid.UUID) -> OptimizationSettings:
    """The organization's row, made with the installation's defaults the first time."""
    row = session.get(OptimizationSettings, org_id, with_for_update=True)
    if row is None:
        s = rt.settings
        row = OptimizationSettings(
            organization_id=org_id,
            min_spend=s.OPTIMIZATION_MIN_SPEND,
            min_conversions=s.OPTIMIZATION_MIN_CONVERSIONS,
            budget_step_percent=s.OPTIMIZATION_BUDGET_STEP_PERCENT,
            cost_jump_percent=s.OPTIMIZATION_COST_JUMP_PERCENT,
            refreshes_used=0,
        )
        session.add(row)
        session.flush()
    return row


def thresholds(settings: Settings, row: OptimizationSettings) -> Thresholds:
    return Thresholds(
        min_spend=row.min_spend,
        min_conversions=row.min_conversions,
        budget_step_percent=row.budget_step_percent,
        cost_jump_percent=row.cost_jump_percent,
        budget_use=settings.OPTIMIZATION_BUDGET_USE,
        winner_factor=settings.OPTIMIZATION_WINNER_FACTOR,
        margin_coverage=settings.OPTIMIZATION_MARGIN_COVERAGE,
    )


def local_today(now: datetime, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


@dataclass(frozen=True)
class Periods:
    first: date
    last: date
    baseline_first: date
    baseline_last: date

    def as_json(self) -> dict[str, str]:
        return {
            "from": self.first.isoformat(),
            "to": self.last.isoformat(),
            "baseline_from": self.baseline_first.isoformat(),
            "baseline_to": self.baseline_last.isoformat(),
        }


def periods(settings: Settings, today: date) -> Periods:
    last = _shift(today, -1)  # complete days only
    first = _shift(last, -(settings.OPTIMIZATION_RECENT_DAYS - 1))
    return Periods(
        first=first,
        last=last,
        baseline_first=_shift(first, -settings.OPTIMIZATION_BASELINE_DAYS),
        baseline_last=_shift(first, -1),
    )


@dataclass
class Found:
    candidates: list[Candidate]
    summary: dict[str, Any]
    currency: str
    step: int


def _margin(session: Session, scope: Scope, p: Periods, fx: FxTable, needed: Decimal) -> Margin:
    found, why, _ = products(session, scope, p.first, p.last, fx)
    if why is not None:
        return Margin(None, None, why.reason or "not_available")
    return margin_of(((f.figures["net_sales"], f.figures["gross_profit"]) for f in found), needed)


def _quiet(rt: Runtime, session: Session, org_id: uuid.UUID, signal: Signal) -> bool:
    """Advice not to show again yet: rejected in the quiet period (unless the loss doubled),
    or approved in the last days."""
    now = rt.clock.now()
    rows = session.execute(
        select(Recommendation.status, Recommendation.decided_at, Recommendation.signal).where(
            Recommendation.organization_id == org_id,
            Recommendation.fingerprint == signal.fingerprint,
            Recommendation.status.in_(("rejected", "approved")),
            Recommendation.decided_at >= now - rt.settings.OPTIMIZATION_QUIET_PERIOD,
        )
    ).all()
    for status, decided_at, stored in rows:
        if status == "approved":
            if decided_at >= now - rt.settings.OPTIMIZATION_ACTED_PERIOD:
                return True
            continue
        old = (stored.get("facts") or {}).get("loss")
        new = signal.facts.get("loss")
        if old is None or new is None or Decimal(new) < Decimal(old) * WORSE:
            return True
    return False


def find(rt: Runtime, session: Session, org_id: uuid.UUID) -> Found:
    """Steps 1 to 3, under the organization's tenant context."""
    s = rt.settings
    org = session.get(Organization, org_id)
    if org is None:
        raise JobSubjectGoneError()
    row = settings_for(rt, session, org_id)
    t = thresholds(s, row)
    now = rt.clock.now()
    scope = load_scope(
        session,
        organization_id=org_id,
        currency=org.default_currency,
        timezone=org.default_timezone,
        now=now,
    )
    p = periods(s, local_today(now, org.default_timezone))
    rules = rules_from(s)
    span = p.last.toordinal() - p.first.toordinal() + 1
    wide_first = min(p.baseline_first, _shift(p.first, -max(span, rules.baseline_days)))
    fx = FxTable.load(session, wide_first, p.last, s.FX_MAX_STALE_DAYS)
    margin = _margin(session, scope, p, fx, t.margin_coverage)
    before = {c.id: c for c in campaigns(session, scope, p.baseline_first, p.baseline_last, fx)}
    signals: list[Signal] = []
    checked = 0
    for c in campaigns(session, scope, p.first, p.last, fx):
        if c.status != "active":
            continue
        checked += 1
        past = before.get(c.id)
        signals += evaluate(
            CampaignInput(
                id=c.id,
                ad_account_id=c.ad_account_id,
                provider=c.provider,
                name=c.name,
                status=c.status,
                recent=c.figures,
                baseline=past.figures if past is not None else {},
            ),
            margin,
            t,
        )
    if scope.ad_accounts or scope.stores:
        funnel = load_funnel(session, scope, load_inputs(session, scope, wide_first, p.last, fx))
        signals += funnel_signals(find_drop_offs(scope, funnel, p.first, p.last, rules))
    found: list[Candidate] = []
    for signal in signals:
        if _quiet(rt, session, org_id, signal):
            continue
        candidate = candidate_for(rt, session, org_id, signal, t.budget_step_percent)
        if candidate is not None:
            found.append(candidate)
    summary = {
        "periods": p.as_json(),
        "campaigns_checked": checked,
        "profit_rules": "used" if margin.reason is None else "skipped",
        "profit_reason": margin.reason,
        "gross_margin": str(margin.value) if margin.value is not None else None,
        "cost_coverage": str(margin.coverage) if margin.coverage is not None else None,
    }
    return Found(found, summary, scope.currency, t.budget_step_percent)


def kinds_now(rt: Runtime, session: Session, org_id: uuid.UUID, campaign_id: uuid.UUID) -> set[str]:
    """The rules that fire for one campaign with today's figures (approval checks again)."""
    s = rt.settings
    org = session.get(Organization, org_id)
    if org is None:
        return set()
    t = thresholds(s, settings_for(rt, session, org_id))
    now = rt.clock.now()
    scope = load_scope(
        session,
        organization_id=org_id,
        currency=org.default_currency,
        timezone=org.default_timezone,
        now=now,
    )
    p = periods(s, local_today(now, org.default_timezone))
    fx = FxTable.load(session, p.baseline_first, p.last, s.FX_MAX_STALE_DAYS)
    margin = _margin(session, scope, p, fx, t.margin_coverage)
    recent = next(
        (c for c in campaigns(session, scope, p.first, p.last, fx) if c.id == campaign_id), None
    )
    if recent is None:
        return set()
    past = next(
        (
            c
            for c in campaigns(session, scope, p.baseline_first, p.baseline_last, fx)
            if c.id == campaign_id
        ),
        None,
    )
    found = evaluate(
        CampaignInput(
            id=recent.id,
            ad_account_id=recent.ad_account_id,
            provider=recent.provider,
            name=recent.name,
            status=recent.status,
            recent=recent.figures,
            baseline=past.figures if past is not None else {},
        ),
        margin,
        t,
    )
    return {f.kind for f in found}


def _explain(
    rt: Runtime, org_id: uuid.UUID, user_id: uuid.UUID | None, found: Found
) -> tuple[list[tuple[Item, dict[str, Any]]], str, uuid.UUID | None, str | None]:
    """Each item with its texts and rank; who explained; the AI run; why not the AI."""
    items = [item_of(i, c, found.currency) for i, c in enumerate(found.candidates)]
    order = sorted(
        items, key=lambda i: (i.candidate.signal.kind == "funnel_drop", -i.candidate.signal.weight)
    )
    rules = [
        (item, {**rules_text(item, rt.settings, found.step), "rank": rank})
        for rank, item in enumerate(order, start=1)
    ]
    if not items:
        return [], "rules", None, None
    try:
        outcome = run_task(
            rt,
            organization_id=org_id,
            user_id=user_id,
            task=optimizer_task(items, rt.settings, found.currency, found.step),
        )
    except AiUnavailableError:
        return rules, "rules", None, "ai_unavailable"
    except AiLimitReached:
        return rules, "rules", None, "ai_limit_reached"
    except AiAnswerRejected:
        return rules, "rules", None, "ai_answer_rejected"
    by_id = {e["id"]: e for e in outcome.data["items"]}
    texts = []
    for item in items:
        e = by_id[item.id]
        texts.append(
            (
                item,
                {
                    "explanation": e["explanation"].strip(),
                    "confidence": e["confidence"],
                    "assumptions": [a.strip() for a in e["assumptions"]],
                    "risks": [r.strip() for r in e["risks"]],
                    "rank": int(e["rank"]),
                },
            )
        )
    return texts, "ai", outcome.run_id, None


def run_look(
    rt: Runtime, org_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Find, explain and keep today's advice; record outcomes. Returns the new advice's ids."""
    with rt.db.transaction(org_id=org_id, user_id=user_id) as session:
        found = find(rt, session, org_id)
    explained, by, run_id, problem = _explain(rt, org_id, user_id, found)
    now = rt.clock.now()
    made: list[uuid.UUID] = []
    with rt.db.transaction(org_id=org_id, user_id=user_id) as session:
        for old in session.execute(
            select(Recommendation)
            .where(Recommendation.organization_id == org_id, Recommendation.status == "open")
            .with_for_update()
        ).scalars():
            old.status = "superseded" if old.expires_at > now else "expired"
            old.closed_reason = "replaced" if old.status == "superseded" else None
            old.updated_at = now
        session.flush()
        actor = Actor("ai_recommendation", None) if by == "ai" else Actor("system", None)
        for item, text in explained:
            c = item.candidate
            rec = Recommendation(
                id=uuid.uuid4(),
                organization_id=org_id,
                kind=c.signal.kind,
                campaign_id=c.signal.campaign_id,
                ad_account_id=c.signal.ad_account_id,
                signal={
                    "figures": c.signal.figures,
                    "facts": c.signal.facts,
                    "written": item.figures,
                    "currency": found.currency,
                    "periods": found.summary["periods"],
                    "note": c.note,
                },
                proposal=c.proposal,
                prechecks=c.prechecks,
                campaign_state=c.campaign_state,
                explanation=text["explanation"],
                confidence=text["confidence"],
                assumptions=text["assumptions"],
                risks=text["risks"],
                rank=text["rank"],
                explained_by=by,
                ai_run_id=run_id,
                status="open",
                expires_at=now + rt.settings.OPTIMIZATION_VALID_FOR,
                fingerprint=c.signal.fingerprint,
                created_at=now,
                updated_at=now,
            )
            session.add(rec)
            session.flush()
            made.append(rec.id)
            record_audit(
                session,
                organization_id=org_id,
                actor=actor,
                action="recommendation.created",
                resource_type="recommendation",
                resource_id=rec.id,
                after={"kind": rec.kind, "proposal": rec.proposal.get("action_type")},
                metadata={
                    "campaign_id": str(rec.campaign_id) if rec.campaign_id else None,
                    "explained_by": by,
                    "ai_run_id": str(run_id) if run_id else None,
                },
            )
        row = settings_for(rt, session, org_id)
        org = session.get(Organization, org_id)
        assert org is not None
        row.last_run_on = local_today(now, org.default_timezone)
        row.last_run_summary = {
            **found.summary,
            "ran_at": now.isoformat(),
            "found": len(made),
            "explained_by": by,
            "ai_problem": problem,
        }
        record_outcomes(rt, session, org)
    logger.info("optimization_look", extra={"organization_id": str(org_id), "found": len(made)})
    return made


# ------------------------------------------------------------------ outcomes (Q-11-9)
def _picked(figures: dict[str, Figure]) -> dict[str, Any]:
    return {
        k: {
            "value": str(figures[k].value) if figures[k].ok else None,
            "availability": figures[k].availability,
            "reason": figures[k].reason,
        }
        for k in OUTCOME_KEYS
        if k in figures
    }


def record_outcomes(rt: Runtime, session: Session, org: Organization) -> int:
    """For each change made from advice and finished at least 7 (14) days ago: the campaign's
    figures over the 7 (14) days before the change and after it."""
    s = rt.settings
    now = rt.clock.now()
    last = _shift(local_today(now, org.default_timezone), -1)
    rows = session.execute(
        select(Recommendation, Action)
        .join(
            Action,
            (Action.recommendation_id == Recommendation.id)
            & (Action.organization_id == Recommendation.organization_id),
        )
        .where(
            Recommendation.organization_id == org.id,
            Action.status == "succeeded",
            Action.finished_at.is_not(None),
        )
    ).all()
    made = 0
    scope: Scope | None = None
    for rec, action in rows:
        assert action.finished_at is not None
        day = local_today(action.finished_at, org.default_timezone)
        have = set(
            session.execute(
                select(RecommendationOutcome.after_days).where(
                    RecommendationOutcome.recommendation_id == rec.id
                )
            ).scalars()
        )
        for n in (7, 14):
            if n in have or _shift(day, n) > last:
                continue
            if scope is None:
                scope = load_scope(
                    session,
                    organization_id=org.id,
                    currency=org.default_currency,
                    timezone=org.default_timezone,
                    now=now,
                )
            fx = FxTable.load(session, _shift(day, -n), _shift(day, n), s.FX_MAX_STALE_DAYS)
            figures: list[dict[str, Any]] = []
            for first, end in (
                (_shift(day, -n), _shift(day, -1)),
                (_shift(day, 1), _shift(day, n)),
            ):
                one = next(
                    (
                        c
                        for c in campaigns(session, scope, first, end, fx)
                        if c.id == rec.campaign_id
                    ),
                    None,
                )
                figures.append(
                    {
                        "from": first.isoformat(),
                        "to": end.isoformat(),
                        "figures": _picked(one.figures) if one else {},
                    }
                )
            session.add(
                RecommendationOutcome(
                    organization_id=org.id,
                    recommendation_id=rec.id,
                    after_days=n,
                    before=figures[0],
                    after=figures[1],
                    created_at=now,
                )
            )
            made += 1
    return made


# ------------------------------------------------------------------ scheduling
def enqueue_looks(rt: Runtime) -> int:
    """Every tick: start the daily look of each organization with an imported ad account
    whose reporting day has passed ``OPTIMIZATION_RUN_HOUR`` and that was not looked at today.
    The list comes from the narrow system-role read of ``ad_accounts`` (0013 grant)."""
    if not rt.settings.OPTIMIZATION_ENABLED:
        return 0
    from app.domains.advertising.models import AdAccount

    with rt.db.transaction(system=True) as session:
        orgs = sorted(
            set(
                session.execute(
                    select(AdAccount.organization_id).where(
                        AdAccount.first_import_completed_at.is_not(None)
                    )
                ).scalars()
            )
        )
    started = 0
    now = rt.clock.now()
    for org_id in orgs:
        with rt.db.transaction(org_id=org_id) as session:
            org = session.get(Organization, org_id)
            if org is None:
                continue
            local = now.astimezone(ZoneInfo(org.default_timezone))
            row = settings_for(rt, session, org_id)
            if local.hour < rt.settings.OPTIMIZATION_RUN_HOUR or row.last_run_on == local.date():
                continue
            row.last_run_on = local.date()  # once a day, even before the job has run
            create_job(
                session,
                rt,
                organization_id=org_id,
                job_type=JOB_LOOK,
                subject_type="organization",
                subject_id=org_id,
                requested_by=None,
            )
            started += 1
    if started:
        logger.info("optimization_looks_started", extra={"count": started})
    return started


def look_job(rt: Runtime, job: ClaimedJob) -> None:
    if job.organization_id is None:
        raise JobSubjectGoneError()
    if not rt.settings.OPTIMIZATION_ENABLED:
        return
    run_look(rt, job.organization_id)
