"""In-process Google sign-in for the Google Ads and GA4 simulators (Phases 3 and 5).

Google's OAuth 2.0 server as documented: the browser-side consent (``approve``), the token
endpoint (code exchange with PKCE S256, refresh, ``invalid_grant``) and token revocation.
The ID token carries only ``iss``, ``aud``, ``sub`` and its times. A refresh returns the
scopes that were granted at sign-in. Records every request. No network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from app.core.clock import Clock

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-google-client-secret-0123456789"


@dataclass
class GoogleOAuthSim:
    clock: Clock
    requests: list[httpx.Request] = field(default_factory=list)
    token_status: int | None = None  # force the token endpoint's status (e.g. 503)
    send_new_refresh_on_refresh: bool = False
    _codes: dict[str, dict[str, str]] = field(default_factory=dict)
    access_tokens: dict[str, tuple[str, float]] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)
    refresh_scopes: dict[str, str] = field(default_factory=dict)
    revoked: list[str] = field(default_factory=list)
    issued: int = 0

    def calls(self, part: str) -> list[httpx.Request]:
        return [r for r in self.requests if part in r.url.path]

    # ------------------------------------------------------------------ browser side
    def approve(
        self,
        authorize_url: str,
        sub: str,
        *,
        scopes: str | None = None,
        declined: bool = False,
    ) -> dict[str, str]:
        """Play the person on Google's consent screen; return the callback parameters."""
        parts = urlsplit(authorize_url)
        assert (parts.hostname, parts.path) == ("accounts.google.com", "/o/oauth2/v2/auth")
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert query["client_id"] == CLIENT_ID
        assert query["access_type"] == "offline"
        assert query["code_challenge_method"] == "S256"
        if declined:
            return {"error": "access_denied", "state": query["state"]}
        granted = scopes if scopes is not None else query["scope"]
        code = f"sim-code-{secrets.token_hex(8)}"
        self._codes[code] = {
            "sub": sub,
            "challenge": query["code_challenge"],
            "redirect_uri": query["redirect_uri"],
            "scope": granted,
        }
        return {"code": code, "state": query["state"], "scope": granted}

    # ------------------------------------------------------------------ server side
    def _id_token(self, sub: str) -> str:
        def part(data: dict[str, Any]) -> str:
            raw = json.dumps(data, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        now = int(self.clock.now().timestamp())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": sub}
        claims |= {"iat": now, "exp": now + 3600}
        return f"{part({'alg': 'RS256', 'typ': 'JWT'})}.{part(claims)}.c2lnbmF0dXJl"

    def _new_access(self, sub: str) -> str:
        self.issued += 1
        token = f"ya29.sim-access-{self.issued}-{secrets.token_hex(6)}"
        self.access_tokens[token] = (sub, self.clock.now().timestamp() + 3599)
        return token

    def _oauth(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if request.url.path == "/revoke":
            token = form.get("token", "")
            if token in self.refresh_tokens:
                sub = self.refresh_tokens.pop(token)
                self.access_tokens = {k: v for k, v in self.access_tokens.items() if v[0] != sub}
                self.revoked.append(token)
                return httpx.Response(200, json={})
            if token in self.access_tokens:
                self.access_tokens.pop(token)
                self.revoked.append(token)
                return httpx.Response(200, json={})
            return httpx.Response(400, json={"error": "invalid_token"})
        if request.url.path != "/token":
            return httpx.Response(404, json={"error": "not_found"})
        if self.token_status is not None:
            return httpx.Response(self.token_status, json={"error": "backend_error"})
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = form.get("grant_type")
        if grant == "authorization_code":
            entry = self._codes.pop(form.get("code", ""), None)
            if entry is None or entry["redirect_uri"] != form.get("redirect_uri"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            verifier = form.get("code_verifier", "")
            digest = hashlib.sha256(verifier.encode()).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != entry["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            refresh = f"1//sim-refresh-{secrets.token_hex(10)}"
            self.refresh_tokens[refresh] = entry["sub"]
            self.refresh_scopes[refresh] = entry["scope"]
            body = {
                "access_token": self._new_access(entry["sub"]),
                "expires_in": 3599,
                "refresh_token": refresh,
                "scope": entry["scope"],
                "token_type": "Bearer",
                "id_token": self._id_token(entry["sub"]),
            }
            return httpx.Response(200, json=body)
        if grant == "refresh_token":
            refresh = form.get("refresh_token", "")
            sub = self.refresh_tokens.get(refresh)
            if sub is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            body = {
                "access_token": self._new_access(sub),
                "expires_in": 3599,
                "scope": self.refresh_scopes.get(refresh, ""),
                "token_type": "Bearer",
            }
            if self.send_new_refresh_on_refresh:
                new = f"1//sim-refresh-{secrets.token_hex(10)}"
                self.refresh_tokens[new] = self.refresh_tokens.pop(refresh)
                self.refresh_scopes[new] = self.refresh_scopes.pop(refresh, "")
                body["refresh_token"] = new
            return httpx.Response(200, json=body)
        return httpx.Response(400, json={"error": "unsupported_grant_type"})
