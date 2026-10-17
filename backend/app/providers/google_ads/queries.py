"""Google Ads Query Language (GAQL) used by AdVegaX — reads only (PHASE_03_PLAN §4, §9).

Field names are from Google's ``customer_client`` / ``customer`` resources (verified against the
v25 reference on 2026-10-15). The JSON shapes of the answers (camelCase keys, int64 values as
strings) are to be confirmed on the test manager account (Step 0 item 1).
"""

from __future__ import annotations

# A manager's own row (level 0) and the accounts directly below it (level 1). Run on every
# manager in turn, with the top manager as ``login-customer-id`` (Google's hierarchy sample).
HIERARCHY = """
SELECT
  customer_client.client_customer,
  customer_client.id,
  customer_client.level,
  customer_client.manager,
  customer_client.descriptive_name,
  customer_client.currency_code,
  customer_client.time_zone,
  customer_client.status
FROM customer_client
WHERE customer_client.level <= 1
""".strip()

# The account's own details (one operation).
ACCOUNT = """
SELECT
  customer.id,
  customer.descriptive_name,
  customer.currency_code,
  customer.time_zone,
  customer.status
FROM customer
""".strip()

# Structure (one operation each; removed items are included so history stays readable).
# Since v23 campaign dates are ``start_date_time`` / ``end_date_time`` ("yyyy-MM-dd HH:mm:ss"
# in the account's time zone; the v22 ``start_date`` / ``end_date`` were removed).
BUDGETS = """
SELECT
  campaign_budget.id,
  campaign_budget.name,
  campaign_budget.amount_micros,
  campaign_budget.total_amount_micros,
  campaign_budget.period,
  campaign_budget.explicitly_shared
FROM campaign_budget
""".strip()

CAMPAIGNS = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.advertising_channel_type,
  campaign.bidding_strategy_type,
  campaign.start_date_time,
  campaign.end_date_time,
  campaign.campaign_budget
FROM campaign
""".strip()

AD_GROUPS = """
SELECT
  ad_group.id,
  ad_group.name,
  ad_group.status,
  ad_group.type,
  ad_group.campaign
FROM ad_group
""".strip()

ADS = """
SELECT
  ad_group_ad.ad.id,
  ad_group_ad.ad.name,
  ad_group_ad.ad.type,
  ad_group_ad.status,
  ad_group_ad.ad_group
FROM ad_group_ad
""".strip()
