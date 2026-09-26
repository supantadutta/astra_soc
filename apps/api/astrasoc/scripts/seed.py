"""CLI: create schema + seed baseline and demo data (idempotent).

    python -m astrasoc.scripts.seed
"""
from __future__ import annotations

from ..config import settings
from ..db import SessionLocal, init_db
from ..seed.bootstrap import ensure_seed
from ..seed.engine import ensure_demo_estate_data


def main() -> None:
    init_db()
    with SessionLocal() as db:
        ensure_seed(db)
        if settings.should_seed_demo_users:
            ensure_demo_estate_data(db)
    print("Seed complete: global registry, root provider"
          + (" + demo MSSP estate." if settings.should_seed_demo_users else "."))


if __name__ == "__main__":
    main()
