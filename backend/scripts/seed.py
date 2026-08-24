"""Database seed script (run manually): creates admin, demo user + API key,
worker, and default models if they don't exist.

Usage:
    PYTHONPATH=. python3.11 scripts/seed.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import AsyncSessionLocal  # noqa: E402
from app.seed import seed_initial  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await seed_initial(db)
        print("Seed complete:", result)


if __name__ == "__main__":
    asyncio.run(main())
