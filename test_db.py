import asyncio

from db.database import async_session_maker
from db.models import User


async def test_insert_user():
    async with async_session_maker() as session:
        user = User(
            telegram_user_id=123456789,
            username="test_user",
            first_name="Test",
            last_name="User",
        )
        session.add(user)
        await session.commit()

        print("Тестовый пользователь успешно добавлен в базу.")


if __name__ == "__main__":
    asyncio.run(test_insert_user())
