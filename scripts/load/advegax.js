// AdVegaX load test (Phase 15, task 15-05, PHASE_15_PLAN Q-15-7). Run against STAGING only:
//
//   k6 run -e API=https://api-staging.example.com -e ORIGIN=https://app-staging.example.com \
//          -e USERS=users.csv scripts/load/advegax.js
//
// users.csv: one "email,password,organization_id" per line — test accounts made for the load
// test (never real customers'). Each virtual person signs in once, then browses the pages'
// API calls with pauses, like a person. Targets: p95 < 500 ms, under 1 % errors.
import http from "k6/http";
import { check, group, sleep } from "k6";
import { SharedArray } from "k6/data";

const API = `${__ENV.API}/api/v1`;
const ORIGIN = __ENV.ORIGIN;
const people = new SharedArray("people", () =>
  open(__ENV.USERS)
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"))
    .map((l) => {
      const [email, password, org] = l.split(",");
      return { email, password, org };
    }),
);

export const options = {
  scenarios: {
    people: {
      executor: "ramping-vus",
      stages: [
        { duration: "2m", target: 50 },
        { duration: "10m", target: 200 },
        { duration: "2m", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
  },
};

function signIn(person) {
  const csrf = http.get(`${API}/auth/csrf`).json("data.csrf_token");
  const res = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email: person.email, password: person.password }),
    { headers: { "Content-Type": "application/json", Origin: ORIGIN, "X-CSRF-Token": csrf } },
  );
  check(res, { "signed in": (r) => r.status === 200 });
}

const PAGES = [
  "",
  "/analytics/overview",
  "/analytics/channels",
  "/analytics/campaigns",
  "/analytics/funnel",
  "/recommendations",
  "/actions",
  "/ad-accounts",
  "/stores",
  "/billing",
];

export default function () {
  const person = people[(__VU - 1) % people.length];
  if (__ITER === 0) signIn(person);
  group("browse", () => {
    for (const page of PAGES) {
      const res = http.get(`${API}/organizations/${person.org}${page}`, { tags: { page } });
      check(res, { ok: (r) => r.status === 200 });
      sleep(1 + Math.random() * 2);
    }
  });
}
