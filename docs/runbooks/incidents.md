# Runbook — Incidents

1. **Contain:** switch off the affected feature (`fly secrets set ACTIONS_ENABLED=false`, `AUTOPILOT_ENABLED=false`, `BILLING_ENABLED=false`, …); "Pause all changes" for one organization in its Settings.
2. **Look:** `fly logs --app advegax-api-staging` (JSON, with request ids; secrets are scrubbed); the audit log of the organization; the error alerts.
3. **Credentials leaked or suspected:** rotate (keys.md); disconnect affected platform connections (owners reconnect); revoke Stripe keys.
4. **Personal data breach:** assess under the Australian Notifiable Data Breaches scheme within 30 days; tell affected organizations; record what happened.
5. **Afterwards:** a short write-up — what happened, impact, fix, how to prevent it.
