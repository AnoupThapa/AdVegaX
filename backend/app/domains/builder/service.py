"""The campaign builder API: drafts, checks, launch, go live, clean up (Phase 10B, 10B-05).

* **Prepare** (owner, admin, manager): a draft for one platform of a **ready** strategy, from
  an **approved** creative, with what AdVegaX can fill in (the daily amount the strategy
  computed, converted to the ad account's currency; the store's country; the product's page).
* **Edit**: until it is launched; every edit adds one to the version and asks for the
  declarations again.
* **Check**: every builder check (``checks.py``), then the platform's test.
* **Launch / Go live / Clean up**: requests to the Action Engine (``launch.py``), approved by
  an owner or admin like any change.

Every change is audited — never the ad text.
"""

from __future__ import annotations

import secrets as token_source
import uuid
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    ActionDuplicate,
    ActionNotAllowed,
    CreativeNotApproved,
    DraftInvalid,
    DraftNotEditable,
    NotFound,
    ServiceUnavailable,
    ValidationFailed,
)
from app.domains.actions import engine
from app.domains.actions.catalogue import quantum
from app.domains.actions.facts import require_switches
from app.domains.actions.models import Action, ActionEvent
from app.domains.actions.schemas import ActionCheckOut, ActionOut, DryRunOut
from app.domains.actions.service import ActionService
from app.domains.actions.validation import Check, failures, passed
from app.domains.advertising.models import AdAccount, AdCampaign
from app.domains.ai.models import CampaignStrategy
from app.domains.audit.service import Actor, record_audit
from app.domains.builder import checks as draft_checks
from app.domains.builder import launch
from app.domains.builder.context import (
    DraftContext,
    account_context,
    build_of,
    builder_for,
    facts,
    has_conversions,
    landing_default,
    load,
    summary,
)
from app.domains.builder.models import CampaignDraft
from app.domains.builder.schemas import (
    CreativeSummaryOut,
    DraftCreateIn,
    DraftOut,
    DraftPreviewOut,
    DraftUpdateIn,
    MetaAssetOut,
)
from app.domains.commerce.models import Product, Store
from app.domains.creative.models import Creative, CreativeSet
from app.domains.creative.service import storage_for
from app.domains.finance.definitions import minor_units
from app.domains.fx.service import FxTable
from app.domains.integrations.tokens import usable_secrets
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.providers.base.changes import COUNTRIES, CampaignChange, CampaignSnapshot, ChangeKind
from app.providers.base.errors import ProviderError
from app.providers.base.types import AdAccountRef, AdEntityStatus
from app.runtime import Runtime

DAYS_PER_MONTH = Decimal("30.4")
# The country a currency's business most likely sells in (the default location, Q-10B-3).
COUNTRY_OF = {
    "AUD": "AU",
    "NZD": "NZ",
    "NPR": "NP",
    "INR": "IN",
    "USD": "US",
    "GBP": "GB",
    "CAD": "CA",
    "SGD": "SG",
    "EUR": "IE",
}


def _reference() -> str:
    return f"AVX-{token_source.token_hex(3).upper()}"


class BuilderService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ helpers
    def _audit(
        self, session: Session, ctx: TenantContext, action: str, draft: CampaignDraft, **more: Any
    ) -> None:
        record_audit(
            session,
            organization_id=ctx.organization_id,
            actor=Actor.user(ctx.user_id),
            action=action,
            resource_type="campaign_draft",
            resource_id=draft.id,
            after=summary(draft),
            metadata={k: v for k, v in more.items() if v is not None},
        )

    def _out(self, session: Session, ctx: TenantContext, c: DraftContext) -> DraftOut:
        d = c.draft
        open_id = launch.open_action(session, ctx.organization_id, d.id)
        campaign_id = None
        if d.created_ids.get("campaign"):
            campaign_id = session.execute(
                select(AdCampaign.id).where(
                    AdCampaign.organization_id == ctx.organization_id,
                    AdCampaign.ad_account_id == d.ad_account_id,
                    AdCampaign.external_campaign_id == d.created_ids["campaign"],
                )
            ).scalar_one_or_none()
        step = quantum(d.currency)
        if d.platform == "google_ads":
            bidding = (
                "maximize_conversions"
                if has_conversions(self.rt, session, c.account)
                else "maximize_clicks"
            )
        else:
            bidding = "purchases" if d.meta_pixel_id else "link_clicks"
        cr = c.creative
        return DraftOut(
            id=d.id,
            strategy_id=d.strategy_id,
            product_title=c.product.title if c.product else None,
            platform=d.platform,
            ad_account_id=d.ad_account_id,
            ad_account_name=c.account.name,
            creative=CreativeSummaryOut(
                id=cr.id,
                version=cr.version,
                status=cr.status,
                format=cr.format,
                angle=cr.angle,
                content=dict(cr.content),
                asset_id=cr.asset_id,
            ),
            name=d.name,
            reference=d.reference,
            daily_budget=str(Decimal(d.daily_budget).quantize(step)),
            monthly_estimate=str(
                (Decimal(d.daily_budget) * DAYS_PER_MONTH).quantize(step, rounding=ROUND_HALF_EVEN)
            ),
            currency=d.currency,
            currency_minor_units=minor_units(d.currency),
            locations=list(d.locations),
            age_min=d.age_min,
            age_max=d.age_max,
            keywords=list(d.keywords),
            landing_url=d.landing_url,
            meta_page_id=d.meta_page_id,
            meta_pixel_id=d.meta_pixel_id,
            bidding=bidding,
            declarations_confirmed=d.declaration_confirmed_at is not None,
            version=d.version,
            status=d.status,
            created_ids=dict(d.created_ids),
            campaign_id=campaign_id,
            error_code=d.error_code,
            editable=d.status == "draft" and open_id is None,
            open_action_id=open_id,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )

    def _approved_creative(
        self,
        session: Session,
        org_id: uuid.UUID,
        strategy_id: uuid.UUID,
        platform: str,
        creative_id: uuid.UUID | None,
    ) -> Creative:
        query = (
            select(Creative)
            .join(
                CreativeSet,
                (CreativeSet.id == Creative.set_id)
                & (CreativeSet.organization_id == Creative.organization_id),
            )
            .where(
                Creative.organization_id == org_id,
                CreativeSet.strategy_id == strategy_id,
                Creative.platform == platform,
                Creative.status == "approved",
            )
            .order_by(Creative.updated_at.desc(), Creative.id)
        )
        if creative_id is not None:
            query = query.where(Creative.id == creative_id)
        found = session.execute(query.limit(1)).scalar_one_or_none()
        if found is None:
            raise CreativeNotApproved()
        return found

    def _ad_account(
        self, session: Session, org_id: uuid.UUID, platform: str, wanted: uuid.UUID | None
    ) -> AdAccount:
        query = select(AdAccount).where(
            AdAccount.organization_id == org_id,
            AdAccount.provider == platform,
            AdAccount.status == "active",
        )
        if wanted is not None:
            query = query.where(AdAccount.id == wanted)
        accounts = list(session.execute(query.order_by(AdAccount.name, AdAccount.id)).scalars())
        if wanted is not None and not accounts:
            raise NotFound()
        if len(accounts) != 1:
            raise ValidationFailed(
                details=[
                    {
                        "field": "ad_account_id",
                        "reason": "choose_ad_account" if accounts else "no_ad_account",
                    }
                ]
            )
        return accounts[0]

    def _budget(
        self, session: Session, strategy: CampaignStrategy, platform: str, currency: str
    ) -> Decimal:
        """The strategy's daily amount for the platform, in the ad account's currency."""
        daily = Decimal(str((strategy.budget_amounts.get(platform) or {}).get("daily") or "0"))
        if daily <= 0:
            return Decimal(1)
        today: date = self.rt.clock.now().date()
        fx = FxTable.load(session, today, today, self.rt.settings.FX_MAX_STALE_DAYS)
        converted = fx.convert(daily, strategy.budget_currency, currency, today)
        if converted is None:
            converted = daily if strategy.budget_currency == currency else Decimal(1)
        step = quantum(currency)
        return max(step, converted.quantize(step, rounding=ROUND_HALF_EVEN))

    # ------------------------------------------------------------------ drafts
    def create(self, ctx: TenantContext, body: DraftCreateIn) -> DraftOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            strategy = session.get(CampaignStrategy, body.strategy_id)
            if strategy is None or strategy.organization_id != ctx.organization_id:
                raise NotFound()
            platforms = [p.get("platform") for p in strategy.strategy.get("platforms", [])]
            if strategy.status != "ready" or body.platform not in platforms:
                raise DraftInvalid(
                    details=[
                        {
                            "check": "creative",
                            "reason": "strategy_not_ready"
                            if strategy.status != "ready"
                            else "platform_not_in_strategy",
                        }
                    ]
                )
            creative = self._approved_creative(
                session, ctx.organization_id, strategy.id, body.platform, body.creative_id
            )
            account = self._ad_account(
                session, ctx.organization_id, body.platform, body.ad_account_id
            )
            product = session.get(Product, strategy.product_id)
            store = session.get(Store, product.store_id) if product else None
            reference = _reference()
            kind = "Search" if body.platform == "google_ads" else "Sales"
            title = (product.title if product else "Campaign")[:120]
            country = COUNTRY_OF.get(account.currency, "AU")
            now = self.rt.clock.now()
            draft = CampaignDraft(
                id=uuid.uuid4(),
                organization_id=ctx.organization_id,
                strategy_id=strategy.id,
                creative_id=creative.id,
                platform=body.platform,
                ad_account_id=account.id,
                name=f"{title} - {kind} - {reference}",
                daily_budget=self._budget(session, strategy, body.platform, account.currency),
                currency=account.currency,
                locations=[country] if country in COUNTRIES else [],
                age_min=18,
                age_max=65,
                keywords=[],
                landing_url=landing_default(store, product),
                reference=reference,
                version=1,
                status="draft",
                created_ids={},
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(draft)
            session.flush()
            self._audit(session, ctx, "campaign_draft.created", draft, strategy_id=str(strategy.id))
            return self._out(session, ctx, load(session, ctx.organization_id, draft.id))

    def get(self, ctx: TenantContext, draft_id: uuid.UUID) -> DraftOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._out(session, ctx, load(session, ctx.organization_id, draft_id))

    def list_drafts(self, ctx: TenantContext, strategy_id: uuid.UUID | None) -> list[DraftOut]:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            query = select(CampaignDraft.id).where(
                CampaignDraft.organization_id == ctx.organization_id,
                CampaignDraft.status != "archived",
            )
            if strategy_id is not None:
                query = query.where(CampaignDraft.strategy_id == strategy_id)
            ids = list(session.execute(query.order_by(CampaignDraft.created_at.desc())).scalars())
            return [self._out(session, ctx, load(session, ctx.organization_id, i)) for i in ids]

    def update(self, ctx: TenantContext, draft_id: uuid.UUID, body: DraftUpdateIn) -> DraftOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            c = load(session, ctx.organization_id, draft_id, lock=True)
            d = c.draft
            if d.status != "draft" or launch.open_action(session, ctx.organization_id, d.id):
                raise DraftNotEditable()
            changed = False
            for field in (
                "name",
                "landing_url",
                "meta_page_id",
                "meta_pixel_id",
                "age_min",
                "age_max",
            ):
                value = getattr(body, field)
                if value is not None and value != getattr(d, field):
                    setattr(d, field, value.strip() if isinstance(value, str) else value)
                    changed = True
            if body.remove_pixel and d.meta_pixel_id is not None:
                d.meta_pixel_id, changed = None, True
            if body.daily_budget is not None and body.daily_budget != d.daily_budget:
                d.daily_budget, changed = body.daily_budget, True
            if body.locations is not None:
                codes = [c_.strip().upper() for c_ in body.locations]
                if codes != list(d.locations):
                    d.locations, changed = codes, True
            if body.keywords is not None:
                words = [
                    {"text": " ".join(k.text.split()), "match": k.match} for k in body.keywords
                ]
                if words != list(d.keywords):
                    d.keywords, changed = words, True
            if body.creative_id is not None and body.creative_id != d.creative_id:
                found = self._approved_creative(
                    session, ctx.organization_id, d.strategy_id, d.platform, body.creative_id
                )
                d.creative_id, changed = found.id, True
            if d.age_min > d.age_max:
                raise DraftInvalid(details=[{"check": "targeting", "reason": "ages_invalid"}])
            if changed:
                d.version += 1
                d.declaration_confirmed_by = d.declaration_confirmed_at = None
            if body.confirm_declarations:
                d.declaration_confirmed_by = ctx.user_id
                d.declaration_confirmed_at = self.rt.clock.now()
            if changed or body.confirm_declarations:
                d.updated_by, d.updated_at = ctx.user_id, self.rt.clock.now()
                session.flush()
                self._audit(
                    session,
                    ctx,
                    "campaign_draft.edited",
                    d,
                    declarations="confirmed" if body.confirm_declarations else None,
                )
            return self._out(session, ctx, load(session, ctx.organization_id, d.id))

    def archive(self, ctx: TenantContext, draft_id: uuid.UUID) -> DraftOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            c = load(session, ctx.organization_id, draft_id, lock=True)
            if c.draft.status != "draft" or launch.open_action(
                session, ctx.organization_id, c.draft.id
            ):
                raise DraftNotEditable()
            c.draft.status, c.draft.updated_at = "archived", self.rt.clock.now()
            self._audit(session, ctx, "campaign_draft.archived", c.draft)
            return self._out(session, ctx, c)

    # ------------------------------------------------------------------ checking
    def _assess(
        self, ctx: TenantContext, draft_id: uuid.UUID
    ) -> tuple[DraftContext, list[Check], dict[str, Any], dict[str, str | None]]:
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            require_switches(self.rt, session, ctx.organization_id)
            c = load(session, ctx.organization_id, draft_id)
            f = facts(self.rt, session, c)
            maximize = has_conversions(self.rt, session, c.account)
        if f.resource_reason in ("changes_not_allowed", "permission_missing"):
            raise ActionNotAllowed(details=[{"reason": f.resource_reason}])
        results = draft_checks.run(f)
        step = quantum(c.draft.currency)
        bounds = {
            "platform_minimum": str(f.minimum.quantize(step, rounding=ROUND_CEILING))
            if f.minimum is not None
            else None,
            "organization_maximum": str(f.maximum.quantize(step, rounding=ROUND_FLOOR))
            if f.maximum is not None
            else None,
        }
        dry: dict[str, Any] = {"result": "skipped"}
        builder = builder_for(self.rt, c.account.provider)
        if passed(results) and builder is not None:
            try:
                image = storage_for(self.rt).get(c.asset_key) if c.asset_key else b""
                build = build_of(c, image=image, maximize_conversions=maximize)
                secrets = usable_secrets(self.rt, ctx.organization_id, c.connection.id)
                engine.platform_call(
                    self.rt,
                    builder,
                    ctx.organization_id,
                    c.connection.id,
                    lambda: builder.create_campaign(
                        secrets, c.ref, build, c.account.currency, validate_only=True
                    ),
                )
                dry = {"result": "passed"}
            except ProviderError as exc:
                dry = {"result": "failed", "reason": exc.code}
            except Exception:
                raise ServiceUnavailable() from None
        return c, results, dry, bounds

    def validate(self, ctx: TenantContext, draft_id: uuid.UUID) -> DraftPreviewOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        _, results, dry, bounds = self._assess(ctx, draft_id)
        return DraftPreviewOut(
            draft=self.get(ctx, draft_id),
            passed=passed(results) and dry.get("result") == "passed",
            checks=[ActionCheckOut(**r.as_json()) for r in results],
            dry_run=DryRunOut(**dry),
            budget_limits=bounds,
        )

    # ------------------------------------------------------------------ requests
    def _request(
        self,
        ctx: TenantContext,
        c: DraftContext,
        action_type: str,
        checks: list[Check],
        dry_run: dict[str, Any],
    ) -> ActionOut:
        try:
            with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
                require_switches(self.rt, session, ctx.organization_id)
                d = session.get(CampaignDraft, c.draft.id, with_for_update=True)
                assert d is not None
                fresh = load(session, ctx.organization_id, d.id)
                reason = launch.preconditions(fresh, action_type)
                if reason is not None or d.version != c.draft.version:
                    raise DraftNotEditable()
                if launch.open_action(session, ctx.organization_id, d.id):
                    raise ActionDuplicate()
                now = self.rt.clock.now()
                action = Action(
                    id=uuid.uuid4(),
                    organization_id=ctx.organization_id,
                    action_type=action_type,
                    provider=c.account.provider,
                    ad_account_id=c.account.id,
                    campaign_id=None,
                    draft_id=d.id,
                    params={"version": str(d.version), "reference": d.reference},
                    currency=d.currency,
                    previous={"status": d.status, "created": sorted(d.created_ids)},
                    status="pending",
                    idempotency_key=f"{d.id}:{action_type}:{d.version}"[:64],
                    checks=[x.as_json() for x in checks],
                    dry_run=dry_run,
                    source="user",
                    requested_by=ctx.user_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(action)
                session.flush()
                session.add(
                    ActionEvent(
                        organization_id=ctx.organization_id,
                        action_id=action.id,
                        seq=1,
                        from_status=None,
                        status="pending",
                        actor_type="user",
                        actor_user_id=ctx.user_id,
                        detail={"draft_id": str(d.id)},
                        created_at=now,
                    )
                )
                record_audit(
                    session,
                    organization_id=ctx.organization_id,
                    actor=Actor.user(ctx.user_id),
                    action="action.requested",
                    resource_type="action",
                    resource_id=action.id,
                    after={"status": "pending"},
                    metadata={
                        "action_type": action_type,
                        "draft_id": str(d.id),
                        "provider": action.provider,
                        "reference": d.reference,
                    },
                )
                action_id = action.id
        except IntegrityError:
            raise ActionDuplicate() from None
        return ActionService(self.rt).get(ctx, action_id)

    def launch(self, ctx: TenantContext, draft_id: uuid.UUID) -> ActionOut:
        """Request creating the campaign, everything paused (approved by an owner or admin)."""
        authorize(ctx, Permission.ACTIONS_REQUEST)
        c, results, dry, _ = self._assess(ctx, draft_id)
        if not passed(results) or dry.get("result") != "passed":
            found = failures(results)
            if dry.get("result") == "failed":
                found.append({"check": "dry_run", "reason": dry.get("reason")})
            raise DraftInvalid(details=found)
        return self._request(ctx, c, launch.CREATE, results, dry)

    def go_live(self, ctx: TenantContext, draft_id: uuid.UUID) -> ActionOut:
        """Request switching the created campaign on (approved by an owner or admin)."""
        authorize(ctx, Permission.ACTIONS_REQUEST)
        c, dry = self._other(ctx, draft_id, launch.GO_LIVE)
        return self._request(ctx, c, launch.GO_LIVE, [Check("draft", "passed")], dry)

    def clean_up(self, ctx: TenantContext, draft_id: uuid.UUID) -> ActionOut:
        """Request removing what a failed launch created (it is paused)."""
        authorize(ctx, Permission.ACTIONS_REQUEST)
        c, dry = self._other(ctx, draft_id, launch.REMOVE)
        return self._request(ctx, c, launch.REMOVE, [Check("draft", "passed")], dry)

    def _other(
        self, ctx: TenantContext, draft_id: uuid.UUID, action_type: str
    ) -> tuple[DraftContext, dict[str, Any]]:
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            require_switches(self.rt, session, ctx.organization_id)
            c = load(session, ctx.organization_id, draft_id)
            reason = launch.preconditions(c, action_type)
            if reason is not None:
                raise DraftInvalid(details=[{"check": "draft", "reason": reason}])
            from app.domains.builder.context import resource_reason

            problem = resource_reason(self.rt, c)
        if problem is not None:
            if problem in ("changes_not_allowed", "permission_missing"):
                raise ActionNotAllowed(details=[{"reason": problem}])
            raise DraftInvalid(details=[{"check": "resource", "reason": problem}])
        dry: dict[str, Any] = {"result": "skipped"}
        builder = builder_for(self.rt, c.account.provider)
        if action_type == launch.GO_LIVE and builder is not None:
            paused = CampaignSnapshot(
                external_id=c.draft.created_ids["campaign"], status=AdEntityStatus.PAUSED
            )
            try:
                secrets = usable_secrets(self.rt, ctx.organization_id, c.connection.id)
                engine.platform_call(
                    self.rt,
                    builder,
                    ctx.organization_id,
                    c.connection.id,
                    lambda: builder.change_campaign(
                        secrets,
                        c.ref,
                        paused,
                        CampaignChange(ChangeKind.RESUME),
                        c.account.currency,
                        validate_only=True,
                    ),
                )
                dry = {"result": "passed"}
            except ProviderError as exc:
                raise DraftInvalid(details=[{"check": "dry_run", "reason": exc.code}]) from None
        return c, dry

    # ------------------------------------------------------------------ Meta assets
    def _meta_assets(
        self, ctx: TenantContext, ad_account_id: uuid.UUID, kind: str
    ) -> list[MetaAssetOut]:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            account, resource, connection, _ = account_context(
                session, ctx.organization_id, ad_account_id
            )
        provider = builder_for(self.rt, account.provider)
        if provider is None or account.provider != "meta_ads":
            raise NotFound()
        try:
            secrets = usable_secrets(self.rt, ctx.organization_id, connection.id)
            ref = AdAccountRef(account.external_account_id, resource.access_hint)
            call = getattr(provider, "list_pages" if kind == "pages" else "list_pixels")
            found = engine.platform_call(
                self.rt,
                provider,
                ctx.organization_id,
                connection.id,
                lambda: call(secrets) if kind == "pages" else call(secrets, ref),
            )
        except ProviderError:
            raise ServiceUnavailable() from None
        return [MetaAssetOut(id=a.id, name=a.name) for a in found]

    def meta_pages(self, ctx: TenantContext, ad_account_id: uuid.UUID) -> list[MetaAssetOut]:
        return self._meta_assets(ctx, ad_account_id, "pages")

    def meta_pixels(self, ctx: TenantContext, ad_account_id: uuid.UUID) -> list[MetaAssetOut]:
        return self._meta_assets(ctx, ad_account_id, "pixels")
