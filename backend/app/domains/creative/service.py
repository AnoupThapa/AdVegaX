"""The creative workflow (Phase 9, task 9-05, PLAN Q-9-6, Q-9-7, Q-9-8; D16, A27).

* **Draft** (all but viewers): from a **ready** strategy, one AI run drafts every platform's
  concepts (``generation.py``); each is kept as version 1, a draft, with its check results.
* **Edit**: only the newest version of a concept that is not archived; an edit adds a new
  draft version (the previous one is kept unchanged, approved or not).
* **Approve / reject / archive** (owner, admin, manager): approving re-runs the fixed checks
  against today's rules and catalogue prices — any blocking result refuses it, and flagged
  wording needs a confirmation; the concept's previously approved version is archived (one
  approved version per concept). A rejection needs a reason.
* **Images**: uploaded, checked by decoding and re-saved clean (``images.py``), stored under
  a random key (``app/core/storage``), read back only through this API by members.
* **Rules**: the organization's own prohibited and allowed-capitalised words (owners, admins).

Every change is audited — with versions, statuses and reasons, never the ad text.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    AssetInvalid,
    CreativeChecksFailed,
    CreativeNotEditable,
    NotFound,
    ValidationFailed,
)
from app.core.storage import Storage, build_storage, new_key
from app.domains.ai.models import CampaignStrategy
from app.domains.ai.runs import run_task
from app.domains.audit.service import Actor, record_audit
from app.domains.commerce.models import Product, ProductVariant
from app.domains.creative.context import build_creative_context
from app.domains.creative.generation import content_of, creative_task
from app.domains.creative.images import ImageRejected, clean_image
from app.domains.creative.models import Creative, CreativeAsset, CreativeRules, CreativeSet
from app.domains.creative.policy import BASE_PROHIBITED, blocking, check, flags
from app.domains.creative.schemas import (
    AssetOut,
    AssetRefOut,
    CheckOut,
    CreativeOut,
    CreativeRulesIn,
    CreativeRulesOut,
    CreativeSetOut,
    CreativeSetSummaryOut,
    CreativeUpdateIn,
    VersionRefOut,
)
from app.domains.creative.specs import FORMAT_OF
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

TERM = re.compile(r"^[\w][\w '#%&+./-]{0,58}[\w%]?$")
CAPS_WORD = re.compile(r"^[A-Za-z0-9]{2,30}$")


def storage_for(rt: Runtime) -> Storage:
    """The configured store (tests put one in ``rt.extras["storage"]``)."""
    found = rt.extras.get("storage")
    if found is None:
        found = build_storage(rt.settings)
        rt.extras["storage"] = found
    return found  # type: ignore[return-value]


def _rules(session: Session, organization_id: uuid.UUID) -> tuple[list[str], list[str]]:
    row = session.get(CreativeRules, organization_id)
    if row is None:
        return [], []
    return list(row.prohibited_terms), list(row.allowed_caps)


def _prices(session: Session, organization_id: uuid.UUID, product_id: uuid.UUID) -> list[Decimal]:
    return sorted(
        {
            p
            for p in session.execute(
                select(ProductVariant.price).where(
                    ProductVariant.organization_id == organization_id,
                    ProductVariant.product_id == product_id,
                    ProductVariant.deleted.is_(False),
                )
            ).scalars()
            if p is not None
        }
    )


def _summary(row: Creative) -> dict[str, Any]:
    """What the audit keeps of a creative: never its text."""
    return {
        "concept_id": str(row.concept_id),
        "version": row.version,
        "status": row.status,
        "platform": row.platform,
        "asset_id": str(row.asset_id) if row.asset_id else None,
    }


class CreativeService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ helpers
    def _audit(
        self,
        session: Session,
        ctx: TenantContext,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_audit(
            session,
            organization_id=ctx.organization_id,
            actor=Actor.user(ctx.user_id),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            metadata=metadata,
        )

    def _creative(
        self, session: Session, ctx: TenantContext, creative_id: uuid.UUID, *, lock: bool = False
    ) -> Creative:
        query = select(Creative).where(
            Creative.organization_id == ctx.organization_id, Creative.id == creative_id
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).scalar_one_or_none()
        if row is None:
            raise NotFound()
        return row

    def _set_facts(
        self, session: Session, ctx: TenantContext, set_id: uuid.UUID
    ) -> tuple[CreativeSet, uuid.UUID, str | None]:
        found = session.execute(
            select(CreativeSet, CampaignStrategy.product_id, Product.title)
            .join(
                CampaignStrategy,
                (CampaignStrategy.id == CreativeSet.strategy_id)
                & (CampaignStrategy.organization_id == CreativeSet.organization_id),
            )
            .outerjoin(
                Product,
                (Product.id == CampaignStrategy.product_id)
                & (Product.organization_id == CampaignStrategy.organization_id),
            )
            .where(CreativeSet.organization_id == ctx.organization_id, CreativeSet.id == set_id)
        ).first()
        if found is None:
            raise NotFound()
        return found[0], found[1], found[2]

    def _out(self, session: Session, ctx: TenantContext, row: Creative) -> CreativeOut:
        cset, product_id, title = self._set_facts(session, ctx, row.set_id)
        versions = list(
            session.execute(
                select(Creative)
                .where(
                    Creative.organization_id == ctx.organization_id,
                    Creative.concept_id == row.concept_id,
                )
                .order_by(Creative.version)
            ).scalars()
        )
        asset = session.get(CreativeAsset, row.asset_id) if row.asset_id else None
        return CreativeOut(
            id=row.id,
            set_id=row.set_id,
            strategy_id=cset.strategy_id,
            product_id=product_id,
            product_title=title,
            concept_id=row.concept_id,
            version=row.version,
            latest=row.version == versions[-1].version,
            platform=row.platform,
            format=row.format,
            angle=row.angle,
            status=row.status,
            content=row.content,
            rationale=row.rationale,
            compliance_notes=[str(n) for n in row.compliance_notes],
            checks=[CheckOut(**c) for c in row.checks],
            approvable=not blocking(row.checks),
            asset=AssetRefOut(
                id=asset.id, content_type=asset.content_type, width=asset.width, height=asset.height
            )
            if asset is not None
            else None,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
            decision_reason=row.decision_reason,
            created_by=row.created_by,
            created_at=row.created_at,
            versions=[
                VersionRefOut(id=v.id, version=v.version, status=v.status, created_at=v.created_at)
                for v in versions
            ],
        )

    def _latest(self, session: Session, ctx: TenantContext, set_id: uuid.UUID) -> list[Creative]:
        newest = (
            select(Creative.concept_id, func.max(Creative.version).label("version"))
            .where(Creative.organization_id == ctx.organization_id, Creative.set_id == set_id)
            .group_by(Creative.concept_id)
            .subquery()
        )
        return list(
            session.execute(
                select(Creative)
                .join(
                    newest,
                    (newest.c.concept_id == Creative.concept_id)
                    & (newest.c.version == Creative.version),
                )
                .where(Creative.organization_id == ctx.organization_id)
                .order_by(Creative.platform, Creative.created_at, Creative.concept_id)
            ).scalars()
        )

    def _set_out(self, session: Session, ctx: TenantContext, set_id: uuid.UUID) -> CreativeSetOut:
        cset, product_id, title = self._set_facts(session, ctx, set_id)
        return CreativeSetOut(
            id=cset.id,
            strategy_id=cset.strategy_id,
            product_id=product_id,
            product_title=title,
            created_at=cset.created_at,
            ai_run_id=cset.ai_run_id,
            creatives=[self._out(session, ctx, c) for c in self._latest(session, ctx, set_id)],
        )

    # ------------------------------------------------------------------ draft
    def generate(self, ctx: TenantContext, strategy_id: uuid.UUID) -> CreativeSetOut:
        authorize(ctx, Permission.CREATIVES_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            context = build_creative_context(
                session, organization_id=ctx.organization_id, strategy_id=strategy_id
            )
            prohibited, caps = _rules(session, ctx.organization_id)
        task = creative_task(context, self.rt.settings, prohibited=prohibited, allowed_caps=caps)
        outcome = run_task(
            self.rt, organization_id=ctx.organization_id, user_id=ctx.user_id, task=task
        )
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            cset = CreativeSet(
                organization_id=ctx.organization_id,
                strategy_id=context.strategy_id,
                ai_run_id=outcome.run_id,
                created_by=ctx.user_id,
                created_at=self.rt.clock.now(),
            )
            session.add(cset)
            session.flush()
            now = self.rt.clock.now()
            count = 0
            for platform in context.platforms:
                for concept in outcome.data[platform]:
                    content = content_of(concept)
                    session.add(
                        Creative(
                            organization_id=ctx.organization_id,
                            set_id=cset.id,
                            concept_id=uuid.uuid4(),
                            version=1,
                            platform=platform,
                            format=FORMAT_OF[platform],
                            angle=concept["angle"].strip(),
                            status="draft",
                            content=content,
                            rationale=concept["rationale"],
                            compliance_notes=list(concept["compliance_notes"]),
                            checks=check(
                                FORMAT_OF[platform],
                                content,
                                prohibited=prohibited,
                                allowed_caps=caps,
                                prices=context.prices,
                            ),
                            created_by=ctx.user_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    count += 1
            session.flush()
            self._audit(
                session,
                ctx,
                "creative_set.generated",
                "creative_set",
                cset.id,
                after={"strategy_id": str(context.strategy_id), "concepts": count},
                metadata={"ai_run_id": outcome.run_id},
            )
            return self._set_out(session, ctx, cset.id)

    # ------------------------------------------------------------------ read
    def get_set(self, ctx: TenantContext, set_id: uuid.UUID) -> CreativeSetOut:
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._set_out(session, ctx, set_id)

    def list_sets(
        self, ctx: TenantContext, strategy_id: uuid.UUID | None
    ) -> list[CreativeSetSummaryOut]:
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            query = (
                select(CreativeSet, Product.title)
                .join(
                    CampaignStrategy,
                    (CampaignStrategy.id == CreativeSet.strategy_id)
                    & (CampaignStrategy.organization_id == CreativeSet.organization_id),
                )
                .outerjoin(
                    Product,
                    (Product.id == CampaignStrategy.product_id)
                    & (Product.organization_id == CampaignStrategy.organization_id),
                )
                .where(CreativeSet.organization_id == ctx.organization_id)
                .order_by(CreativeSet.created_at.desc(), CreativeSet.id)
                .limit(100)
            )
            if strategy_id is not None:
                query = query.where(CreativeSet.strategy_id == strategy_id)
            out = []
            for cset, title in session.execute(query).all():
                rows = session.execute(
                    select(Creative.concept_id, Creative.status).where(
                        Creative.organization_id == ctx.organization_id,
                        Creative.set_id == cset.id,
                    )
                ).all()
                out.append(
                    CreativeSetSummaryOut(
                        id=cset.id,
                        strategy_id=cset.strategy_id,
                        product_title=title,
                        created_at=cset.created_at,
                        concepts=len({c for c, _ in rows}),
                        approved=len({c for c, s in rows if s == "approved"}),
                    )
                )
            return out

    def get(self, ctx: TenantContext, creative_id: uuid.UUID) -> CreativeOut:
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._out(session, ctx, self._creative(session, ctx, creative_id))

    def list_creatives(
        self,
        ctx: TenantContext,
        *,
        status: str | None,
        platform: str | None,
        strategy_id: uuid.UUID | None,
    ) -> list[CreativeOut]:
        """With ``status=approved``: what the campaign builder (10B) may use."""
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            query = select(Creative).where(Creative.organization_id == ctx.organization_id)
            if status is not None:
                query = query.where(Creative.status == status)
            if platform is not None:
                query = query.where(Creative.platform == platform)
            if strategy_id is not None:
                query = query.join(
                    CreativeSet,
                    (CreativeSet.id == Creative.set_id)
                    & (CreativeSet.organization_id == Creative.organization_id),
                ).where(CreativeSet.strategy_id == strategy_id)
            rows = session.execute(
                query.order_by(Creative.created_at.desc(), Creative.id).limit(200)
            ).scalars()
            return [self._out(session, ctx, r) for r in rows]

    # ------------------------------------------------------------------ change
    def update(
        self, ctx: TenantContext, creative_id: uuid.UUID, body: CreativeUpdateIn
    ) -> CreativeOut:
        authorize(ctx, Permission.CREATIVES_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._creative(session, ctx, creative_id, lock=True)
            newest = session.execute(
                select(func.max(Creative.version)).where(
                    Creative.organization_id == ctx.organization_id,
                    Creative.concept_id == row.concept_id,
                )
            ).scalar_one()
            if row.status == "archived" or row.version != newest:
                raise CreativeNotEditable()
            content = body.content if body.content is not None else row.content
            asset_id = None if body.remove_asset else (body.asset_id or row.asset_id)
            if asset_id is not None:
                if row.platform != "meta_ads":
                    raise ValidationFailed(details=[{"field": "asset_id", "issue": "meta_only"}])
                asset = session.execute(
                    select(CreativeAsset).where(
                        CreativeAsset.organization_id == ctx.organization_id,
                        CreativeAsset.id == asset_id,
                    )
                ).scalar_one_or_none()
                if asset is None or (asset.status != "active" and asset_id != row.asset_id):
                    raise ValidationFailed(
                        details=[{"field": "asset_id", "issue": "unknown_asset"}]
                    )
            _, product_id, _ = self._set_facts(session, ctx, row.set_id)
            prohibited, caps = _rules(session, ctx.organization_id)
            results = check(
                row.format,
                content,
                prohibited=prohibited,
                allowed_caps=caps,
                prices=_prices(session, ctx.organization_id, product_id),
            )
            if any(r["code"] == "shape" for r in results):
                raise ValidationFailed(
                    details=[{"field": "content", "issue": f"shape:{r['field']}"} for r in results]
                )
            now = self.rt.clock.now()
            new = Creative(
                organization_id=ctx.organization_id,
                set_id=row.set_id,
                concept_id=row.concept_id,
                version=row.version + 1,
                replaces_id=row.id,
                platform=row.platform,
                format=row.format,
                angle=row.angle,
                status="draft",
                content=content,
                rationale=row.rationale,
                compliance_notes=row.compliance_notes,
                checks=results,
                asset_id=asset_id,
                created_by=ctx.user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(new)
            session.flush()
            self._audit(
                session,
                ctx,
                "creative.edited",
                "creative",
                new.id,
                before=_summary(row),
                after=_summary(new),
            )
            return self._out(session, ctx, new)

    def approve(self, ctx: TenantContext, creative_id: uuid.UUID, *, confirm: bool) -> CreativeOut:
        authorize(ctx, Permission.CREATIVES_APPROVE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._creative(session, ctx, creative_id, lock=True)
            if row.status == "approved":
                return self._out(session, ctx, row)
            if row.status != "draft":
                raise CreativeNotEditable()
            _, product_id, _ = self._set_facts(session, ctx, row.set_id)
            prohibited, caps = _rules(session, ctx.organization_id)
            results = check(
                row.format,
                row.content,
                prohibited=prohibited,
                allowed_caps=caps,
                prices=_prices(session, ctx.organization_id, product_id),
            )
            row.checks = results  # today's rules and prices
            failed = blocking(results)
            pending = flags(results) if not confirm else []
            if failed or pending:
                session.flush()
                raise CreativeChecksFailed(
                    details=[
                        {
                            "reason": r["code"],
                            "field": r["field"],
                            "detail": r["detail"],
                            "severity": r["severity"],
                        }
                        for r in [*failed, *pending]
                    ]
                )
            before = _summary(row)
            now = self.rt.clock.now()
            for old in session.execute(
                select(Creative).where(
                    Creative.organization_id == ctx.organization_id,
                    Creative.concept_id == row.concept_id,
                    Creative.status == "approved",
                )
            ).scalars():
                old.status, old.updated_at = "archived", now
                self._audit(
                    session,
                    ctx,
                    "creative.archived",
                    "creative",
                    old.id,
                    after=_summary(old),
                    metadata={"replaced_by": row.id},
                )
            session.flush()
            row.status, row.decided_by, row.decided_at, row.updated_at = (
                "approved",
                ctx.user_id,
                now,
                now,
            )
            row.decision_reason = None
            session.flush()
            self._audit(
                session,
                ctx,
                "creative.approved",
                "creative",
                row.id,
                before=before,
                after=_summary(row),
                metadata={"flags_confirmed": [r["detail"] for r in flags(results)]},
            )
            return self._out(session, ctx, row)

    def reject(self, ctx: TenantContext, creative_id: uuid.UUID, reason: str) -> CreativeOut:
        authorize(ctx, Permission.CREATIVES_APPROVE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._creative(session, ctx, creative_id, lock=True)
            if row.status != "draft":
                raise CreativeNotEditable()
            before = _summary(row)
            now = self.rt.clock.now()
            row.status, row.decided_by, row.decided_at, row.updated_at = (
                "rejected",
                ctx.user_id,
                now,
                now,
            )
            row.decision_reason = " ".join(reason.split())[:500]
            session.flush()
            self._audit(
                session,
                ctx,
                "creative.rejected",
                "creative",
                row.id,
                before=before,
                after=_summary(row),
                metadata={"reason": row.decision_reason},
            )
            return self._out(session, ctx, row)

    def archive(self, ctx: TenantContext, creative_id: uuid.UUID) -> CreativeOut:
        authorize(ctx, Permission.CREATIVES_APPROVE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._creative(session, ctx, creative_id, lock=True)
            if row.status != "archived":
                before = _summary(row)
                row.status, row.updated_at = "archived", self.rt.clock.now()
                session.flush()
                self._audit(
                    session,
                    ctx,
                    "creative.archived",
                    "creative",
                    row.id,
                    before=before,
                    after=_summary(row),
                )
            return self._out(session, ctx, row)

    # ------------------------------------------------------------------ images
    @staticmethod
    def _asset_out(row: CreativeAsset) -> AssetOut:
        return AssetOut(
            id=row.id,
            content_type=row.content_type,
            width=row.width,
            height=row.height,
            bytes=row.bytes,
            sha256=row.sha256,
            original_name=row.original_name,
            status=row.status,
            uploaded_by=row.uploaded_by,
            created_at=row.created_at,
        )

    def upload(self, ctx: TenantContext, name: str | None, data: bytes) -> AssetOut:
        authorize(ctx, Permission.CREATIVES_MANAGE)
        s = self.rt.settings
        try:
            image = clean_image(
                data,
                max_bytes=s.ASSET_MAX_BYTES,
                min_side=s.ASSET_MIN_SIDE,
                max_pixels=s.ASSET_MAX_PIXELS,
            )
        except ImageRejected as exc:
            raise AssetInvalid(details=[{"reason": exc.reason}]) from None
        key = new_key(ctx.organization_id, image.content_type)
        storage_for(self.rt).put(key, image.content, image.content_type)
        shown = " ".join((name or "").split())[:255] or None
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            now = self.rt.clock.now()
            row = CreativeAsset(
                organization_id=ctx.organization_id,
                storage_key=key,
                content_type=image.content_type,
                width=image.width,
                height=image.height,
                bytes=len(image.content),
                sha256=image.sha256,
                original_name=shown,
                status="active",
                uploaded_by=ctx.user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            self._audit(
                session,
                ctx,
                "creative_asset.uploaded",
                "creative_asset",
                row.id,
                after={"content_type": row.content_type, "bytes": row.bytes, "sha256": row.sha256},
            )
            return self._asset_out(row)

    def list_assets(self, ctx: TenantContext, *, archived: bool) -> list[AssetOut]:
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rows = session.execute(
                select(CreativeAsset)
                .where(
                    CreativeAsset.organization_id == ctx.organization_id,
                    CreativeAsset.status == ("archived" if archived else "active"),
                )
                .order_by(CreativeAsset.created_at.desc(), CreativeAsset.id)
                .limit(200)
            ).scalars()
            return [self._asset_out(r) for r in rows]

    def _asset(self, session: Session, ctx: TenantContext, asset_id: uuid.UUID) -> CreativeAsset:
        row = session.execute(
            select(CreativeAsset).where(
                CreativeAsset.organization_id == ctx.organization_id, CreativeAsset.id == asset_id
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound()
        return row

    def content(self, ctx: TenantContext, asset_id: uuid.UUID) -> tuple[bytes, str]:
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._asset(session, ctx, asset_id)
            key, kind = row.storage_key, row.content_type
        return storage_for(self.rt).get(key), kind

    def archive_asset(self, ctx: TenantContext, asset_id: uuid.UUID) -> AssetOut:
        authorize(ctx, Permission.CREATIVES_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._asset(session, ctx, asset_id)
            if row.status != "archived":
                row.status, row.updated_at = "archived", self.rt.clock.now()
                session.flush()
                self._audit(
                    session,
                    ctx,
                    "creative_asset.archived",
                    "creative_asset",
                    row.id,
                    after={"status": "archived"},
                )
            return self._asset_out(row)

    # ------------------------------------------------------------------ rules
    def get_rules(self, ctx: TenantContext) -> CreativeRulesOut:
        authorize(ctx, Permission.CREATIVES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = session.get(CreativeRules, ctx.organization_id)
            return CreativeRulesOut(
                prohibited_terms=list(row.prohibited_terms) if row else [],
                allowed_caps=list(row.allowed_caps) if row else [],
                base_prohibited_terms=list(BASE_PROHIBITED),
                updated_at=row.updated_at if row else None,
            )

    def put_rules(self, ctx: TenantContext, body: CreativeRulesIn) -> CreativeRulesOut:
        authorize(ctx, Permission.ORG_UPDATE)
        terms = list(dict.fromkeys(" ".join(t.lower().split()) for t in body.prohibited_terms))
        caps = list(dict.fromkeys(w.strip().upper() for w in body.allowed_caps))
        bad = [
            {"field": "prohibited_terms", "issue": "invalid_term"}
            for t in terms
            if not TERM.fullmatch(t)
        ] + [
            {"field": "allowed_caps", "issue": "invalid_word"}
            for w in caps
            if not CAPS_WORD.fullmatch(w)
        ]
        if bad:
            raise ValidationFailed(details=bad[:1])
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = session.get(CreativeRules, ctx.organization_id)
            before = (
                {"prohibited_terms": row.prohibited_terms, "allowed_caps": row.allowed_caps}
                if row
                else None
            )
            now = self.rt.clock.now()
            if row is None:
                row = CreativeRules(organization_id=ctx.organization_id)
                session.add(row)
            row.prohibited_terms, row.allowed_caps = terms, caps
            row.updated_by, row.updated_at = ctx.user_id, now
            session.flush()
            self._audit(
                session,
                ctx,
                "creative_rules.updated",
                "creative_rules",
                ctx.organization_id,
                before=before,
                after={"prohibited_terms": terms, "allowed_caps": caps},
            )
        return self.get_rules(ctx)
