"""Make a person an AdVegaX administrator (Phase 16, task 16-03).

    uv run python -m app.domains.platform.make_admin you@example.com

The person must have an account (signed up in the web app). They then open /admin, switch
two-step sign-in on with an authenticator app, and enter its code at each sign-in.
"""

from __future__ import annotations

import sys

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.settings import get_settings
from app.domains.identity.models import User
from app.domains.platform.models import PlatformAdmin
from app.runtime import build_runtime


def make(email: str) -> bool:
    rt = build_runtime(get_settings())
    try:
        with rt.db.transaction(system=True) as session:
            user_id = session.execute(
                select(User.id).where(User.email == email.strip().lower())
            ).scalar_one_or_none()
            if user_id is None:
                return False
            session.execute(insert(PlatformAdmin).values(user_id=user_id).on_conflict_do_nothing())
        return True
    finally:
        rt.close()


def main() -> int:  # pragma: no cover - a command for people, exercised through ``make``
    if len(sys.argv) != 2:
        print("Usage: python -m app.domains.platform.make_admin <email>")
        return 2
    if not make(sys.argv[1]):
        print("No account with that email. Sign up in the web app first.")
        return 1
    print(f"{sys.argv[1]} is now an AdVegaX administrator. Open /admin to finish set-up.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
