import asyncio
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.types import Update
from fastapi.testclient import TestClient
from pydantic import SecretStr

from linksift.application.ingestion import MaterialIngestionService
from linksift.entrypoints.api import app
from linksift.entrypoints.bot import create_dispatcher
from tests.fakes import FakeMaterialRepository

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


def make_update(
    *, update_id: int, user_id: int, text: str, chat_type: str = "private", is_bot: bool = False
) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 0,
                "chat": {"id": user_id, "type": chat_type},
                "from": {"id": user_id, "is_bot": is_bot, "first_name": "User"},
                "text": text,
            },
        }
    )


def test_liveness():
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_public_users_are_isolated_and_duplicates_are_scoped_per_owner():
    async def run() -> None:
        repository = FakeMaterialRepository()
        dispatcher = create_dispatcher(MaterialIngestionService(repository))
        bot = Bot(token=TOKEN)
        bot.session = AsyncMock()

        await dispatcher.feed_update(
            bot, make_update(update_id=1, user_id=100, text="https://youtu.be/abc")
        )
        await dispatcher.feed_update(
            bot,
            make_update(
                update_id=2,
                user_id=100,
                text="https://www.youtube.com/watch?v=abc&utm_source=test",
            ),
        )
        await dispatcher.feed_update(
            bot, make_update(update_id=3, user_id=200, text="https://youtu.be/abc")
        )

        assert len(repository.materials) == 2
        assert len(repository.attempts) == 2
        assert len(await repository.list_history(owner_telegram_id=100)) == 1
        assert len(await repository.list_history(owner_telegram_id=200)) == 1

    asyncio.run(run())


def test_group_and_bot_messages_are_ignored():
    async def run() -> None:
        repository = FakeMaterialRepository()
        dispatcher = create_dispatcher(MaterialIngestionService(repository))
        bot = Bot(token=TOKEN)
        bot.session = AsyncMock()

        await dispatcher.feed_update(
            bot,
            make_update(update_id=1, user_id=100, text="group text", chat_type="group"),
        )
        await dispatcher.feed_update(
            bot, make_update(update_id=2, user_id=200, text="bot text", is_bot=True)
        )

        assert not repository.materials
        bot.session.assert_not_called()

    asyncio.run(run())


def test_rate_limit_is_per_user():
    async def run() -> None:
        repository = FakeMaterialRepository()
        dispatcher = create_dispatcher(MaterialIngestionService(repository))
        bot = Bot(token=TOKEN)
        bot.session = AsyncMock()

        for index in range(11):
            await dispatcher.feed_update(
                bot, make_update(update_id=index + 1, user_id=100, text=f"note {index}")
            )
        await dispatcher.feed_update(
            bot, make_update(update_id=20, user_id=200, text="another user")
        )

        assert len(await repository.list_history(owner_telegram_id=100)) == 10
        assert len(await repository.list_history(owner_telegram_id=200)) == 1

    asyncio.run(run())


def test_startup_registers_bot_and_disposes_engine(monkeypatch):
    from linksift.entrypoints import bot as bot_module

    class FakeEngine:
        def __init__(self) -> None:
            self.dispose = AsyncMock()

    class FakeBot:
        def __init__(self, token: str) -> None:
            assert token == TOKEN
            self.get_me = AsyncMock(
                return_value=type("BotIdentity", (), {"id": 123, "username": "linksift_bot"})()
            )
            self.delete_webhook = AsyncMock()
            self.set_my_commands = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class FakeDispatcher:
        def __init__(self) -> None:
            self.start_polling = AsyncMock()

    engine = FakeEngine()
    fake_bot = FakeBot(TOKEN)
    dispatcher = FakeDispatcher()
    settings = type(
        "FakeSettings",
        (),
        {"bot_token": SecretStr(TOKEN), "database_url": SecretStr("postgresql+psycopg://db")},
    )()
    monkeypatch.setattr(bot_module, "Settings", lambda: settings)
    monkeypatch.setattr(bot_module, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(bot_module, "create_session_factory", lambda _: object())
    monkeypatch.setattr(bot_module, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(bot_module, "create_dispatcher", lambda _: dispatcher)

    asyncio.run(bot_module.main())

    fake_bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
    fake_bot.set_my_commands.assert_awaited_once()
    dispatcher.start_polling.assert_awaited_once_with(fake_bot, close_bot_session=False)
    engine.dispose.assert_awaited_once()
