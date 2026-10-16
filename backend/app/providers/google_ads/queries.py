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
