"""CLI: create schema + seed baseline and demo data (idempotent).

    python -m astrasoc.scripts.seed
"""
from __future__ import annotations

from ..db import SessionLocal, init_db
from ..seed.bootstrap import ensure_seed
from ..seed.engine import ensure_demo_data


def main() -> None:
    init_db()
    with SessionLocal() as db:
        tenant = ensure_seed(db)
        ensure_demo_data(db, tenant.id)
    print("Seed complete: baseline RBAC/config + demo scenarios.")


if __name__ == "__main__":
    main()
