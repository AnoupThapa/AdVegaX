# Phase 12 — Controlled Autopilot

**Status:** Not started · **Depends on:** 11 + proven 10A in assisted mode · **Milestone:** M5

## Prerequisite decisions
Initial allowed action classes; default limits; who may enable (Manager default **No**).

## Milestones
1. Policies per organization / ad account / campaign / action class: max daily spend, max ± budget %, min campaign age, min conversions, max actions/day, cooldowns
2. Cumulative-change limits over time windows (prevent compounding)
3. Enable/disable with role check and explicit confirmation; global kill switch
4. Monitoring and alerts; automatic disable on anomalies
5. Staged rollout (internal accounts first)

## Note
Platforms can over-deliver against daily budgets on a given day [VERIFY]; "max daily spend" is enforced as a budget-setting limit plus monitoring, not a guarantee.

## Exit criteria
Limit-breach, cooldown and kill-switch tests pass; every automatic action audited with the policy that allowed it.
