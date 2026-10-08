"""Test helpers: a browser-like API client and account factories."""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.domains.notifications.email import memory
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORIGIN = "http://localhost:3000"
PASSWORD = "correct horse battery staple"
TOKEN_RE = re.compile(r"#token=([A-Za-z0-9_\-]+)")


def last_email(to: str, subject_contains: str = "") -> Any:
    for message in reversed(memory.SENT):
        if message.recipient == to and subject_contains in message.subject:
            return message
    raise AssertionError(f"no email to {to!r} containing {subject_contains!r}")


def token_from(message: Any) -> str:
    match = TOKEN_RE.search(message.text)
    assert match, "email contains no token link"
    return match.group(1)


class ApiClient:
    """Behaves like the web app: cookies, Origin header and an in-memory CSRF token."""

    def __init__(self, app: FastAPI) -> None:
        self.http = TestClient(app, base_url="http://testserver")
        self.csrf: str | None = None

    def close(self) -> None:
        self.http.close()

    def refresh_csrf(self) -> str:
        response = self.http.get("/api/v1/auth/csrf")
        assert response.status_code == 200
        self.csrf = response.json()["data"]["csrf_token"]
        return self.csrf

    def _headers(self, extra: dict[str, str] | None) -> dict[str, str]:
        if self.csrf is None:
            self.refresh_csrf()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf or ""}
        headers.update(extra or {})
        return headers

    def get(self, path: str, **kw: Any) -> Any:
        return self.http.get(f"/api/v1{path}", **kw)

    def _send(
        self, method: str, path: str, json: Any = None, headers: dict[str, str] | None = None
    ) -> Any:
        response = self.http.request(
            method, f"/api/v1{path}", json=json, headers=self._headers(headers)
        )
        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json().get("data")
            if isinstance(data, dict) and "csrf_token" in data:
                self.csrf = data["csrf_token"]
        return response

    def post(self, path: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self._send("POST", path, json, headers)

    def patch(self, path: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self._send("PATCH", path, json, headers)

    def delete(self, path: str, headers: dict[str, str] | None = None) -> Any:
        return self._send("DELETE", path, None, headers)

    # -- flows -----------------------------------------------------------------------
    def register(self, email: str, password: str = PASSWORD, name: str | None = None) -> Any:
        body: dict[str, Any] = {"email": email, "password": password}
        if name:
            body["display_name"] = name
        return self.post("/auth/register", body)

    def verify(self, email: str) -> Any:
        return self.post("/auth/verify-email", {"token": token_from(last_email(email, "Verify"))})

    def login(self, email: str, password: str = PASSWORD) -> Any:
        return self.post("/auth/login", {"email": email, "password": password})

    def signup(self, email: str, *, verified: bool = True, name: str | None = None) -> None:
        assert self.register(email, name=name).status_code == 202
        if verified:
            assert self.verify(email).status_code == 200
        assert self.login(email).status_code == 200

    def create_org(self, name: str = "Acme Pty Ltd", **extra: Any) -> dict[str, Any]:
        body = {
            "name": name,
            "default_currency": "AUD",
            "default_timezone": "Australia/Sydney",
            **extra,
        }
        response = self.post("/organizations", body)
        assert response.status_code == 201, response.text
        return dict(response.json()["data"])

    def invite_and_join(self, org_id: str, invitee: ApiClient, email: str, role: str) -> str:
        response = self.post(f"/organizations/{org_id}/invitations", {"email": email, "role": role})
        assert response.status_code == 201, response.text
        token = token_from(last_email(email, "invited"))
        accepted = invitee.post("/invitations/accept", {"token": token})
        assert accepted.status_code == 200, accepted.text
        members = self.get(f"/organizations/{org_id}/members").json()["data"]
        return str(next(m["id"] for m in members if m["email"] == email))


def new_uuid() -> str:
    return str(uuid.uuid4())
