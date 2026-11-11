"""Seed the demo profile. Run: cd /app/backend && python seed.py"""

import asyncio

from lib.db import client, ensure_indexes
from lib.demo import ensure_demo_profile


async def main() -> None:
    await ensure_indexes()
    user = await ensure_demo_profile()
    print(f"Demo profile ready: {user['login']} ({user['id']})")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
