# Performance audit

**Scope limit:** load testing (10, 50 and 100 users) was **not approved** for this audit, so capacity is _Not Verified_. Everything below is single-user measurement on a 2-CPU local machine with the demo data set. That data set is small, so these figures are a lower bound, not a forecast.

## API latency (15 sequential requests each, signed in, demo organization)

| Endpoint             |      Median |          p95 |                 Max |
| -------------------- | ----------: | -----------: | ------------------: |
| `GET /auth/me`       |      6.9 ms |      11.0 ms | 112 ms (first call) |
| `GET /organizations` |      9.6 ms |      10.9 ms |             11.2 ms |
| Overview, 30 days    |     23.5 ms |      32.9 ms | 133 ms (first call) |
| Overview, 90 days    |     22.3 ms |      26.7 ms |             29.0 ms |
| Channels report      |     20.8 ms |      26.8 ms |             27.2 ms |
| Funnel               | **62.0 ms** | **212.7 ms** |              221 ms |
| Recommendations      |     22.0 ms |      25.8 ms |              230 ms |
| Changes (actions)    |     25.7 ms |      31.6 ms |             38.9 ms |
| Audit log            |     15.0 ms |      23.4 ms |             24.2 ms |

The funnel is the slowest endpoint and the most variable. It is the first candidate for profiling once real data exists.

## Web bundle (production build)

- JavaScript chunks: 1.50 MB raw, **425 KB gzip** across all routes. The largest chunk is 230 KB raw (72 KB gzip).
- Fonts: 9 woff2 files, 224 KB in total. They are split by character range, so a page loads only what it uses.
- Product screenshots are served in 480, 800 and 1200 px WebP widths.

## Page performance (from Phase 17 measurements, not re-run)

Lighthouse, mobile profile, slow network:

| Page            | Score | LCP       | Target               |
| --------------- | ----- | --------- | -------------------- |
| Landing         | 97    | 2.3–2.6 s | ≤ 2.5 s (borderline) |
| Overview        | 80–84 | 3.8–3.9 s | **missed**           |
| Reports         | 89–91 | 3.1–3.2 s | **missed**           |
| Recommendations | 93–94 | 2.8 s     | **missed**           |

Layout shift is 0.006–0.07, which is good. INP has not been measured: it is a field metric (QA-006).

## Scalability review (code)

- **Connection pooling:** separate pools for the app and system roles, sized by `DATABASE_POOL_SIZE`. Pre-ping recovered automatically after a PostgreSQL restart (failure test).
- **Unbounded queries:** the Admin organizations list has no limit, and Admin people stops silently at 500 (QA-011). Changes are paged at 50, and the analytics reads are bounded by date range.
- **Index coverage:** see QA-017. Retention and organization deletion should be checked with `EXPLAIN` at scale.
- **Background work:** each scheduled task runs as a singleton. Imports page through provider results, with per-provider rate-limit handling (`tests/providers/test_ratelimit.py`).
- **Capacity:** the k6 script exists (Phase 15) but has never been run against a deployed stack (QA-001).

## Not verified

- Concurrent users.
- Memory and CPU under load.
- Worker throughput.
- Large tenants (100k+ orders).
- CDN and hosting latency.
- Real-device INP.
