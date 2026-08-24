
import asyncio, sys
sys.path.insert(0, "/root/humanllm/backend")
from app.database import AsyncSessionLocal
from app.models import User
from sqlalchemy import select
async def m():
    async with AsyncSessionLocal() as s:
        r = await s.scalars(select(User))
        print("USERS:", [(u.username, u.role, u.is_active) for u in r])
asyncio.run(m())
