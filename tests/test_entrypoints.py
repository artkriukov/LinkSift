import asyncio
from unittest.mock import AsyncMock

from aiogram.types import Update
from fastapi.testclient import TestClient

from linksift.config import Settings
from linksift.entrypoints.api import app
from linksift.entrypoints.bot import create_dispatcher


def test_liveness():
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unauthorized_update_never_reaches_telegram_api():
    from aiogram import Bot

    async def run():
        bot = Bot(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        bot.session = AsyncMock()
        dispatcher = create_dispatcher(Settings(_env_file=None, allowed_user_ids=[999]))
        update = Update.model_validate(
            {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "date": 0,
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 123, "is_bot": False, "first_name": "User"},
                    "text": "/start",
                },
            }
        )
        await dispatcher.feed_update(bot, update)
        bot.session.assert_not_called()

    asyncio.run(run())
