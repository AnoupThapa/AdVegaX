"""In-process Google sign-in and Google Ads API simulator for tests (Phase 3, PLAN §14).

Speaks the documented formats (verified 2026-10-15) behind the real ``SafeHttpClient`` (a
fake resolver returns a public address; the transport is ``httpx.MockTransport``):

* Google's OAuth 2.0 server, shared with the GA4 simulator (``tests/google_oauth_sim.py``);
* Google Ads REST: ``customers:listAccessibleCustomers``, ``googleAds:search`` (paged with
  ``nextPageToken``) and ``googleAds:searchStream``, with the ``developer-token`` and
  ``login-customer-id`` rules, access through manager accounts, test vs production accounts,
  and errors in Google's ``GoogleAdsFailure`` shape;
* changes (Phase 10A): ``campaigns:mutate`` (status) and ``campaignBudgets:mutate``
  (``amountMicros``) with one ``update`` operation, ``updateMask`` and ``validateOnly``; one
  campaign read with its budget (``WHERE campaign.id = …``); and the outcomes a worker must
  survive — an answer lost after the change was made, a timeout before it, a server error.

GAQL is not parsed here: tests (and later tasks' fixtures) register a ``query_handler`` that
answers the queries AdVegaX sends. Records every request. No network — CI never calls Google.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from app.providers.google_ads.provider import GoogleAdsProvider
from app.providers.http.client import OutboundPolicy, SafeHttpClient

from tests.google_oauth_sim import CLIENT_ID, CLIENT_SECRET, GoogleOAuthSim

DEVELOPER_TOKEN = "test-developer-token-ABCDEFGH"
API_VERSION = "v25"
ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
PUBLIC_IP = "142.250.70.10"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)
STRUCTURE = {
    "campaign_budget": "budgets",
    "campaign": "campaigns",
    "ad_group": "ad_groups",
    "ad_group_ad": "ads",
}
# FROM resource of a daily-figures query (one with ``segments.date``) → AdVegaX level.
PERFORMANCE_LEVELS = {
    "customer": "account",
    "campaign": "campaign",
    "ad_group": "ad_group",
    "ad_group_ad": "ad",
}
_BETWEEN = re.compile(r"segments\.date BETWEEN '(\d{4}-\d{2}-\d{2})' AND '(\d{4}-\d{2}-\d{2})'")
_MUTATE = re.compile(r"/customers/([0-9]+)/(campaigns|campaignBudgets):mutate")
_ONE_CAMPAIGN = re.compile(r"WHERE campaign\.id = ([0-9]+)")
_NAME_LIKE = re.compile(r"WHERE campaign\.name LIKE '%([A-Z0-9-]+)%'")
_BULK = re.compile(r"/customers/([0-9]+)/googleAds:mutate")
_RESULT_OF = {
    "campaignBudgetOperation": ("campaignBudgetResult", "campaignBudgets"),
    "campaignOperation": ("campaignResult", "campaigns"),
    "campaignCriterionOperation": ("campaignCriterionResult", "campaignCriteria"),
    "adGroupOperation": ("adGroupResult", "adGroups"),
    "adGroupCriterionOperation": ("adGroupCriterionResult", "adGroupCriteria"),
    "adGroupAdOperation": ("adGroupAdResult", "adGroupAds"),
}
FAILURE_TYPE = f"type.googleapis.com/google.ads.googleads.{API_VERSION}.errors.GoogleAdsFailure"


@dataclass
class Customer:
    id: str
    name: str = "Eve Zone Ads"
    currency: str = "AUD"
    timezone: str = "Australia/Sydney"
    manager: bool = False
    status: str = "ENABLED"  # ENABLED | CANCELED | SUSPENDED | CLOSED
    test: bool = True
    children: list[str] = field(default_factory=list)  # for managers: directly linked ids
    # Structure rows exactly as Google's REST API returns them (see ``sample_structure``).
    budgets: list[dict[str, Any]] = field(default_factory=list)
    campaigns: list[dict[str, Any]] = field(default_factory=list)
    ad_groups: list[dict[str, Any]] = field(default_factory=list)
    ads: list[dict[str, Any]] = field(default_factory=list)
    # Daily-figure rows per level ("account", "campaign", "ad_group", "ad"), see ``perf_row``.
    performance: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Keywords and locations created by the builder (10B).
    criteria: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GoogleUser:
    sub: str
    direct: list[str] = field(default_factory=list)  # customer ids with direct access


QueryHandler = Callable[["GoogleAdsSim", str, str, str | None], list[dict[str, Any]]]


def _no_rows(sim: GoogleAdsSim, customer_id: str, query: str, login: str | None) -> list[Any]:
    return []


@dataclass
class GoogleAdsSim(GoogleOAuthSim):
    customers: dict[str, Customer] = field(default_factory=dict)
    users: dict[str, GoogleUser] = field(default_factory=dict)
    developer_token: str = DEVELOPER_TOKEN
    token_access: str = "test"  # test | explorer | basic | standard
    query_handler: QueryHandler = _no_rows
    page_size: int = 10_000
    stream_batch_size: int = 10_000
    # Forced failures: the next Google Ads call answers this (status, errorCode dict) once.
    fail_next: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    # Changes (10A): what was applied, and how the next change requests end:
    # "lose_answer" (made, then the answer is lost), "timeout" (not made), "server_error",
    # "refuse" (a platform refusal) and "ignore" (answers success, changes nothing).
    mutations: list[dict[str, Any]] = field(default_factory=list)
    change_outcomes: list[str] = field(default_factory=list)
    issued_ids: int = 0

    # ------------------------------------------------------------------ setup helpers
    def add_customer(self, customer_id: str, **kw: Any) -> Customer:
        customer = Customer(customer_id, **kw)
        self.customers[customer_id] = customer
        return customer

    def add_user(self, sub: str, *direct: str) -> GoogleUser:
        user = GoogleUser(sub, list(direct))
        self.users[sub] = user
        return user

    def reachable(self, sub: str, login: str | None) -> set[str]:
        """Accounts the user can call with this ``login-customer-id`` (Google's access model)."""
        user = self.users.get(sub)
        if user is None:
            return set()
        if not login:  # without login-customer-id only direct access counts
            return set(user.direct)
        if login not in user.direct and not any(login in self._below(d) for d in user.direct):
            return set()
        return {login, *self._below(login)}

    def _below(self, customer_id: str) -> set[str]:
        found: set[str] = set()
        stack = list(self.customers.get(customer_id, Customer(customer_id)).children)
        while stack:
            child = stack.pop()
            if child not in found:
                found.add(child)
                stack.extend(self.customers.get(child, Customer(child)).children)
        return found

    # ------------------------------------------------------------------ server side
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        if host == "oauth2.googleapis.com":
            return self._oauth(request)
        if host == "googleads.googleapis.com":
            return self._ads(request)
        return httpx.Response(404, text="not found")

    @staticmethod
    def failure(status: int, error_code: dict[str, str]) -> httpx.Response:
        names = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED"}
        names |= {429: "RESOURCE_EXHAUSTED", 500: "INTERNAL"}
        detail = {
            "@type": FAILURE_TYPE,
            "errors": [{"errorCode": error_code, "message": "Simulated Google Ads error."}],
            "requestId": "sim-request",
        }
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": status,
                    "message": "Request contains an invalid argument.",
                    "status": names.get(status, "UNKNOWN"),
                    "details": [detail],
                }
            },
        )

    def _ads(self, request: httpx.Request) -> httpx.Response:
        prefix = f"/{API_VERSION}"
        path = request.url.path
        if not path.startswith(prefix):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        route = path[len(prefix) :]
        if self.fail_next:
            status, error_code = self.fail_next.pop(0)
            return self.failure(status, error_code)
        if request.headers.get("developer-token") != self.developer_token:
            return self.failure(401, {"authenticationError": "DEVELOPER_TOKEN_INVALID"})
        bearer = request.headers.get("authorization", "")
        entry = self.access_tokens.get(bearer.removeprefix("Bearer "))
        if not bearer.startswith("Bearer ") or entry is None:
            return self.failure(401, {"authenticationError": "OAUTH_TOKEN_INVALID"})
        sub, expires = entry
        if expires < self.clock.now().timestamp():
            return self.failure(401, {"authenticationError": "OAUTH_TOKEN_EXPIRED"})
        if route == "/customers:listAccessibleCustomers" and request.method == "GET":
            user = self.users.get(sub)
            if user is None or not user.direct:
                return self.failure(403, {"authenticationError": "NOT_ADS_USER"})
            return httpx.Response(
                200, json={"resourceNames": [f"customers/{c}" for c in user.direct]}
            )
        if request.method != "POST" or not route.startswith("/customers/"):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        bulk = _BULK.fullmatch(route)
        if bulk:
            return self._bulk(request, sub, bulk.group(1))
        change = _MUTATE.fullmatch(route)
        if change:
            return self._mutate(request, sub, change.group(1), change.group(2))
        customer_id, _, method = route.removeprefix("/customers/").partition("/googleAds:")
        if method not in ("search", "searchStream"):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        login = request.headers.get("login-customer-id")
        customer = self.customers.get(customer_id)
        if customer is None or customer_id not in self.reachable(sub, login):
            return self.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        if not customer.test and self.token_access == "test":
            return self.failure(403, {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"})
        if customer.status != "ENABLED":
            return self.failure(403, {"authorizationError": "CUSTOMER_NOT_ENABLED"})
        body = json.loads(request.content or b"{}")
        query = str(body.get("query", ""))
        if not query.strip().upper().startswith("SELECT"):
            return self.failure(400, {"queryError": "UNEXPECTED_END_OF_QUERY"})
        found = re.search(r"\bFROM\s+(\w+)", query)
        resource = found.group(1) if found else ""
        if "segments.date" in query and resource in PERFORMANCE_LEVELS:
            rows = self.performance_rows(customer, PERFORMANCE_LEVELS[resource], query)
        elif resource == "campaign" and (like := _NAME_LIKE.search(query)):
            rows = [
                {"campaign": dict(r["campaign"])}
                for r in customer.campaigns
                if like.group(1) in str(r.get("campaign", {}).get("name", ""))
            ]
        elif resource == "campaign" and (one := _ONE_CAMPAIGN.search(query)):
            rows = self.campaign_with_budget(customer, one.group(1))
        elif resource == "customer_client":
            rows = self.hierarchy_rows(customer_id)
        elif resource == "customer":
            rows = [self.account_row(customer)]
        elif resource in STRUCTURE:
            rows = list(getattr(customer, STRUCTURE[resource]))
        else:
            rows = self.query_handler(self, customer_id, query, login)
        if method == "searchStream":
            size = max(1, self.stream_batch_size)
            batches = [rows[i : i + size] for i in range(0, len(rows), size)] or [[]]
            return httpx.Response(
                200,
                json=[{"results": b, "fieldMask": "x", "requestId": "sim"} for b in batches],
            )
        start = int(body.get("pageToken") or 0)
        page = rows[start : start + self.page_size]
        answer: dict[str, Any] = {"results": page, "fieldMask": "x"}
        if start + self.page_size < len(rows):
            answer["nextPageToken"] = str(start + self.page_size)
        return httpx.Response(200, json=answer)

    def campaign_with_budget(self, customer: Customer, campaign_id: str) -> list[dict[str, Any]]:
        for row in customer.campaigns:
            data = row.get("campaign", {})
            if data.get("id") != campaign_id:
                continue
            out: dict[str, Any] = {"campaign": dict(data)}
            for budget in customer.budgets:
                if budget["campaignBudget"].get("resourceName") == data.get("campaignBudget"):
                    out["campaignBudget"] = dict(budget["campaignBudget"])
            return [out]
        return []

    def _mutate(
        self, request: httpx.Request, sub: str, customer_id: str, resources: str
    ) -> httpx.Response:
        login = request.headers.get("login-customer-id")
        customer = self.customers.get(customer_id)
        if customer is None or customer_id not in self.reachable(sub, login):
            return self.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        if not customer.test and self.token_access == "test":
            return self.failure(403, {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"})
        if customer.status != "ENABLED":
            return self.failure(403, {"authorizationError": "CUSTOMER_NOT_ENABLED"})
        body = json.loads(request.content or b"{}")
        operations = body.get("operations")
        if not isinstance(operations, list) or len(operations) != 1:
            return self.failure(400, {"requestError": "BAD_REQUEST"})
        rows = customer.campaigns if resources == "campaigns" else customer.budgets
        if "remove" in operations[0]:
            name = operations[0]["remove"]
            key = "campaign" if resources == "campaigns" else "campaignBudget"
            found = [r for r in rows if r.get(key, {}).get("resourceName") == name]
            if not found:
                return self.failure(400, {"mutateError": "RESOURCE_NOT_FOUND"})
            if resources == "campaigns":
                found[0][key]["status"] = "REMOVED"
            else:
                rows.remove(found[0])
            self.mutations.append({"resources": resources, "remove": name})
            return httpx.Response(200, json={"results": [{"resourceName": name}]})
        update, mask = operations[0].get("update"), operations[0].get("updateMask")
        key = "campaign" if resources == "campaigns" else "campaignBudget"
        target = next(
            (
                r[key]
                for r in rows
                if r.get(key, {}).get("resourceName") == update.get("resourceName")
            ),
            None,
        )
        if target is None:
            return self.failure(400, {"mutateError": "RESOURCE_NOT_FOUND"})
        if resources == "campaigns":
            if mask != "status" or update.get("status") not in ("ENABLED", "PAUSED"):
                return self.failure(400, {"fieldMaskError": "FIELD_NOT_FOUND"})
            if target.get("status") == "REMOVED":
                return self.failure(
                    400,
                    {"operationAccessDeniedError": "OPERATION_NOT_PERMITTED_FOR_REMOVED_RESOURCE"},
                )
            changes = {"status": update["status"]}
        else:
            micros = str(update.get("amountMicros", ""))
            if mask != "amountMicros" or not micros.isdigit():
                return self.failure(400, {"fieldMaskError": "FIELD_NOT_FOUND"})
            if int(micros) <= 0 or int(micros) % 10_000:
                return self.failure(
                    400, {"campaignBudgetError": "NON_MULTIPLE_OF_MINIMUM_CURRENCY_UNIT"}
                )
            changes = {"amountMicros": micros}
        if body.get("validateOnly"):
            return httpx.Response(200, json={})
        outcome = self.change_outcomes.pop(0) if self.change_outcomes else "ok"
        if outcome == "timeout":
            raise httpx.ReadTimeout("simulated timeout")
        if outcome == "server_error":
            return self.failure(500, {"internalError": "INTERNAL_ERROR"})
        if outcome == "refuse":
            return self.failure(400, {"campaignError": "CANNOT_MODIFY_CAMPAIGN"})
        if outcome == "ignore":  # answers success but the campaign stays as it was
            return httpx.Response(200, json={"results": [{"resourceName": update["resourceName"]}]})
        target.update(changes)
        self.mutations.append({"resources": resources, **changes})
        if outcome == "lose_answer":
            raise httpx.ReadTimeout("simulated lost answer")
        return httpx.Response(200, json={"results": [{"resourceName": update["resourceName"]}]})

    def _bulk(self, request: httpx.Request, sub: str, customer_id: str) -> httpx.Response:
        """``googleAds:mutate`` (10B): every operation or none; temporary resource names."""
        login = request.headers.get("login-customer-id")
        customer = self.customers.get(customer_id)
        if customer is None or customer_id not in self.reachable(sub, login):
            return self.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        if not customer.test and self.token_access == "test":
            return self.failure(403, {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"})
        body = json.loads(request.content or b"{}")
        operations = body.get("mutateOperations") or []
        base = f"customers/{customer_id}"
        names: dict[str, str] = {}
        made: list[tuple[str, str, dict[str, Any]]] = []  # (operation, resources, row)
        for op in operations:
            ((kind, inner),) = op.items()
            create = dict(inner.get("create") or {})
            result, resources = _RESULT_OF[kind]
            for key in ("campaignBudget", "campaign", "adGroup"):
                if create.get(key) in names:
                    create[key] = names[create[key]]
                elif key in create and str(create[key]).endswith(("/-1", "/-2", "/-3")):
                    return self.failure(400, {"mutateError": "RESOURCE_NOT_FOUND"})
            self.issued_ids += 1
            new_id = str(800000 + self.issued_ids)
            name = f"{base}/{resources}/{new_id}"
            if "resourceName" in create:
                names[create["resourceName"]] = name
            create["resourceName"] = name
            create["id"] = new_id
            if kind == "campaignOperation":
                if "containsEuPoliticalAdvertising" not in create:
                    return self.failure(400, {"fieldError": "REQUIRED"})
                taken = {
                    r["campaign"].get("name")
                    for r in customer.campaigns
                    if r["campaign"].get("status") != "REMOVED"
                }
                if create.get("name") in taken:
                    return self.failure(400, {"campaignError": "DUPLICATE_CAMPAIGN_NAME"})
            if kind == "adGroupAdOperation":
                rsa = create.get("ad", {}).get("responsiveSearchAd", {})
                urls = create.get("ad", {}).get("finalUrls") or []
                if (
                    not 3 <= len(rsa.get("headlines", [])) <= 15
                    or not 2 <= len(rsa.get("descriptions", [])) <= 4
                ):
                    return self.failure(400, {"adError": "TOO_FEW_HEADLINES"})
                if not urls or not str(urls[0]).startswith("https://"):
                    return self.failure(400, {"adError": "INVALID_URL"})
            made.append((kind, result, create))
        if body.get("validateOnly"):
            return httpx.Response(200, json={})
        outcome = self.change_outcomes.pop(0) if self.change_outcomes else "ok"
        if outcome == "timeout":
            raise httpx.ReadTimeout("simulated timeout")
        if outcome == "server_error":
            return self.failure(500, {"internalError": "INTERNAL_ERROR"})
        if outcome == "refuse":
            return self.failure(400, {"campaignError": "CANNOT_CREATE_CAMPAIGN"})
        for kind, _, row in made:
            if kind == "campaignBudgetOperation":
                customer.budgets.append({"campaignBudget": {**row, "period": "DAILY"}})
            elif kind == "campaignOperation":
                customer.campaigns.append({"campaign": row})
            elif kind == "adGroupOperation":
                customer.ad_groups.append({"adGroup": row})
            elif kind == "adGroupAdOperation":
                ad = {**row["ad"], "id": row["id"], "type": "RESPONSIVE_SEARCH_AD"}
                customer.ads.append(
                    {
                        "adGroupAd": {
                            "resourceName": row["resourceName"],
                            "status": row["status"],
                            "adGroup": row["adGroup"],
                            "ad": ad,
                        }
                    }
                )
            else:
                customer.criteria.append(row)
        self.mutations.append({"resources": "googleAds", "operations": len(made)})
        if outcome == "lose_answer":
            raise httpx.ReadTimeout("simulated lost answer")
        return httpx.Response(
            200,
            json={
                "mutateOperationResponses": [
                    {result: {"resourceName": row["resourceName"]}} for _, result, row in made
                ]
            },
        )

    @staticmethod
    def performance_rows(customer: Customer, level: str, query: str) -> list[dict[str, Any]]:
        """The stored rows of ``level`` whose day lies in the query's BETWEEN range (Google
        sends nothing for a day or entity without activity)."""
        found = _BETWEEN.search(query)
        if found is None:
            return []
        first, last = found.groups()
        return [
            r
            for r in customer.performance.get(level, [])
            if first <= str(r.get("segments", {}).get("date", "")) <= last
        ]

    def client_row(self, customer: Customer, level: int) -> dict[str, Any]:
        """A ``customer_client`` row as Google's REST API sends it (camelCase, int64 strings)."""
        return {
            "customerClient": {
                "resourceName": f"customers/{customer.id}/customerClients/{customer.id}",
                "clientCustomer": f"customers/{customer.id}",
                "id": customer.id,
                "level": str(level),
                "manager": customer.manager,
                "descriptiveName": customer.name,
                "currencyCode": customer.currency,
                "timeZone": customer.timezone,
                "status": customer.status,
            }
        }

    @staticmethod
    def account_row(customer: Customer) -> dict[str, Any]:
        return {
            "customer": {
                "resourceName": f"customers/{customer.id}",
                "id": customer.id,
                "descriptiveName": customer.name,
                "currencyCode": customer.currency,
                "timeZone": customer.timezone,
                "status": customer.status,
            }
        }

    def hierarchy_rows(self, customer_id: str) -> list[dict[str, Any]]:
        """``WHERE customer_client.level <= 1``: the account itself and its direct children."""
        me = self.customers[customer_id]
        rows = [self.client_row(me, 0)]
        for child in me.children:
            if child in self.customers:
                rows.append(self.client_row(self.customers[child], 1))
        return rows

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )


def build_provider(sim: GoogleAdsSim, *, burst: int = 1000) -> GoogleAdsProvider:
    """The test clock is frozen, so the per-connection limiter never refills: tests get a
    large burst unless they test the limit itself (pass ``burst=10``, the real value)."""
    provider = GoogleAdsProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        developer_token=DEVELOPER_TOKEN,
        api_version=API_VERSION,
        http_factory=sim.http_factory,
        clock=sim.clock,
    )
    rate, _ = provider.rate_limit
    provider.rate_limit = (rate, burst)
    return provider


def sample_hierarchy(sim: GoogleAdsSim) -> GoogleAdsSim:
    """Agency manager 9000000001 → retail manager 9000000002 → two advertiser accounts (AUD in
    Sydney, NZD in Auckland); plus 1000000003 with direct access, and a cancelled account."""
    sim.add_customer("9000000001", name="Agency", manager=True, children=["9000000002"])
    sim.add_customer(
        "9000000002", name="Retail clients", manager=True, children=["1000000001", "1000000002"]
    )
    sim.add_customer("1000000001", name="Eve Zone AU")
    sim.add_customer("1000000002", name="Eve Zone NZ", currency="NZD", timezone="Pacific/Auckland")
    sim.add_customer("1000000003", name="Mediflex", currency="AUD")
    sim.add_customer("1000000004", name="Old account", status="CANCELED")
    sim.add_user("108000000000000000001", "9000000001", "1000000003", "1000000004")
    return sim


def sample_structure(customer: Customer) -> Customer:
    """Two campaigns in Google's REST format: a Search campaign with a shared daily budget of
    AUD 50.00, one enabled and one removed ad group, and two ads; and a Performance Max
    campaign (no ad groups) with a total budget of AUD 1,234.56 that has ended. Plus a paused
    campaign that was removed, and one row Google might add that AdVegaX cannot read."""
    cid = customer.id
    base = f"customers/{cid}"
    customer.budgets = [
        {
            "campaignBudget": {
                "resourceName": f"{base}/campaignBudgets/501",
                "id": "501",
                "name": "Gloves daily",
                "amountMicros": "50000000",
                "period": "DAILY",
                "explicitlyShared": True,
            }
        },
        {
            "campaignBudget": {
                "resourceName": f"{base}/campaignBudgets/502",
                "id": "502",
                "name": "Spring push",
                "totalAmountMicros": "1234560000",
                "period": "CUSTOM_PERIOD",
                "explicitlyShared": False,
            }
        },
    ]
    customer.campaigns = [
        {
            "campaign": {
                "resourceName": f"{base}/campaigns/11",
                "id": "11",
                "name": "Gloves - Search",
                "status": "ENABLED",
                "advertisingChannelType": "SEARCH",
                "biddingStrategyType": "MAXIMIZE_CONVERSIONS",
                "startDateTime": "2026-01-15 00:00:00",
                "campaignBudget": f"{base}/campaignBudgets/501",
            }
        },
        {
            "campaign": {
                "resourceName": f"{base}/campaigns/12",
                "id": "12",
                "name": "Spring - PMax",
                "status": "PAUSED",
                "advertisingChannelType": "PERFORMANCE_MAX",
                "biddingStrategyType": "MAXIMIZE_CONVERSION_VALUE",
                "startDateTime": "2026-03-01 00:00:00",
                "endDateTime": "2026-05-31 23:59:59",
                "campaignBudget": f"{base}/campaignBudgets/502",
            }
        },
        {
            "campaign": {
                "resourceName": f"{base}/campaigns/13",
                "id": "13",
                "name": "Old test",
                "status": "REMOVED",
                "advertisingChannelType": "DISPLAY",
                "biddingStrategyType": "MANUAL_CPC",
            }
        },
        {"campaign": {"id": "14", "name": "Future type", "status": "SOMETHING_NEW"}},
    ]
    customer.ad_groups = [
        {
            "adGroup": {
                "resourceName": f"{base}/adGroups/2101",
                "id": "2101",
                "name": "Nitrile gloves",
                "status": "ENABLED",
                "type": "SEARCH_STANDARD",
                "campaign": f"{base}/campaigns/11",
            }
        },
        {
            "adGroup": {
                "resourceName": f"{base}/adGroups/2102",
                "id": "2102",
                "name": "Vinyl gloves",
                "status": "REMOVED",
                "type": "SEARCH_STANDARD",
                "campaign": f"{base}/campaigns/11",
            }
        },
    ]
    customer.ads = [
        {
            "adGroupAd": {
                "resourceName": f"{base}/adGroupAds/2101~90001",
                "status": "ENABLED",
                "adGroup": f"{base}/adGroups/2101",
                "ad": {"id": "90001", "type": "RESPONSIVE_SEARCH_AD"},
            }
        },
        {
            "adGroupAd": {
                "resourceName": f"{base}/adGroupAds/2102~90002",
                "status": "PAUSED",
                "adGroup": f"{base}/adGroups/2102",
                "ad": {"id": "90002", "type": "RESPONSIVE_SEARCH_AD", "name": "Vinyl RSA"},
            }
        },
    ]
    return customer


def perf_row(
    day: str,
    *,
    campaign: str | None = None,
    ad_group: str | None = None,
    ad: str | None = None,
    impressions: int = 0,
    clicks: int = 0,
    cost_micros: int = 0,
    conversions: float | str = 0,
    conversions_value: float | str = 0,
) -> dict[str, Any]:
    """One daily-figures row as Google's REST API sends it: int64 values as strings, money in
    micros, and — proto3 JSON — metrics that are zero left out entirely."""
    metrics: dict[str, Any] = {}
    for key, value in (
        ("impressions", str(impressions) if impressions else None),
        ("clicks", str(clicks) if clicks else None),
        ("costMicros", str(cost_micros) if cost_micros else None),
        ("conversions", conversions if conversions else None),
        ("conversionsValue", conversions_value if conversions_value else None),
    ):
        if value is not None:
            metrics[key] = value
    row: dict[str, Any] = {"segments": {"date": day}, "metrics": metrics}
    if campaign is not None:
        row["campaign"] = {"resourceName": f"customers/1/campaigns/{campaign}", "id": campaign}
    if ad_group is not None:
        row["adGroup"] = {"resourceName": f"customers/1/adGroups/{ad_group}", "id": ad_group}
    if ad is not None:
        row["adGroupAd"] = {"ad": {"id": ad}}
    return row


def sample_performance(customer: Customer, search_day: str, pmax_day: str) -> Customer:
    """Figures for two days: on ``search_day`` the Search campaign 11 (ad group 2101, ad 90001)
    spends AUD 12.345678 with 1.5 conversions; on ``pmax_day`` the Performance Max campaign 12
    (no ad groups) has impressions only. Account rows are Google's totals for those days."""
    search = {
        "impressions": 1200,
        "clicks": 34,
        "cost_micros": 12_345_678,
        "conversions": 1.5,
        "conversions_value": 89.9,
    }
    customer.performance = {
        "account": [perf_row(search_day, **search), perf_row(pmax_day, impressions=500)],
        "campaign": [
            perf_row(search_day, campaign="11", **search),
            perf_row(pmax_day, campaign="12", impressions=500),
        ],
        "ad_group": [perf_row(search_day, campaign="11", ad_group="2101", **search)],
        "ad": [perf_row(search_day, campaign="11", ad_group="2101", ad="90001", **search)],
    }
    return customer
