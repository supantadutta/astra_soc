"""CLI: reset & reseed DEMO-scoped data (LIVE data is never touched).

    python -m astrasoc.scripts.reset
"""
from __future__ import annotations

from ..db import SessionLocal, init_db
from ..seed.bootstrap import ensure_seed
from ..seed.engine import reset_demo


def main() -> None:
    init_db()
    with SessionLocal() as db:
        tenant = ensure_seed(db)
        result = reset_demo(db, tenant.id)
    print(f"Demo reset complete: {result}")


if __name__ == "__main__":
    main()
