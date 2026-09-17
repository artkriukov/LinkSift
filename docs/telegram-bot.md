# Telegram-бот LinkSift

Этот документ описывает текущий контракт Telegram ingestion. Его нужно обновлять
вместе с поведением бота, схемой данных или новыми командами.

## Что умеет текущая версия

Бот работает через aiogram long polling и открыт всем пользователям в личных чатах.
Регистрация, allowlist и ручной ввод Telegram ID не используются. Поддерживаются:

- `/start` — краткое приветствие;
- `/help` — возможности и текущие ограничения;
- `/history` — последние 10 активных материалов только текущего пользователя;
- одно текстовое сообщение длиной до 20 000 символов;
- одна HTTP/HTTPS-ссылка в сообщении.

Фото, видео, аудио, voice, документы, стикеры, контакты и геолокация не скачиваются.
Группы, supergroups, каналы и сообщения от других ботов игнорируются.

## Поток одного сообщения

```text
Telegram Message
  → PrivateChatMiddleware
  → RateLimitMiddleware (10 материалов / 60 секунд / user ID)
  → handler
  → MaterialIngestionService
  → MaterialRepository
  → одна PostgreSQL-транзакция: material + processing attempt
```

Владелец всегда определяется как `message.from_user.id`. ID не читается из текста,
команд или callback data. Repository-запросы поиска и истории обязательно получают
`owner_telegram_id`; поэтому совпадающая ссылка у двух пользователей создаёт две
независимые записи.

При старте процесс проверяет `LINKSIFT_BOT_TOKEN` и `LINKSIFT_DATABASE_URL`, создаёт
async SQLAlchemy engine, удаляет старый webhook, регистрирует команды и запускает
polling. При остановке закрываются Telegram session и database engine. Для одного
token должен работать только один polling-процесс.

## Подготовка и дедупликация

`application/ingestion.py` отвечает за разбор, а не Telegram handler. Для URL он:

1. допускает только `http` и `https`, запрещает встроенные username/password;
2. ограничивает длину 2048 символами;
3. приводит scheme и hostname к нижнему регистру, убирает fragment и стандартный port;
4. убирает завершающий slash, сортирует query и удаляет UTM, `fbclid`, `gclid`;
5. приводит варианты `youtu.be` и `youtube.com/watch` к одному каноническому URL;
6. вычисляет SHA-256 канонического URL.

Полный присланный URL хранится в `source_url`. Для обычного текста повторяющиеся
пробельные символы схлопываются только перед SHA-256; исходный текст сохраняется в
`source_text`. Пользовательское содержимое никогда не помещается в `source_key`.

Тип определяется без сетевого запроса: `youtube`, `instagram_reel`, `direct_media`,
`article` или `text`. Бот не открывает ссылку и не скачивает содержимое.

Активная уникальность задаётся парой `owner_telegram_id + source_key`. Повторная
отправка возвращает существующий статус без новой строки и попытки. После soft delete
источник можно сохранить снова. Уникальный индекс в PostgreSQL закрывает также гонку
двух одновременных сообщений.

## Запись в базу

Новый материал и попытка создаются методом
`create_material_with_attempt()` в одной транзакции:

```text
materials.status = pending
processing_attempts.attempt_number = 1
processing_attempts.status = pending
processing_attempts.pipeline_version = telegram-ingestion-v1
```

Ошибка создания попытки откатывает материал. `/history` исключает soft-deleted записи,
сортирует новые выше старых и HTML-экранирует отображаемые значения.

## Безопасность и наблюдаемость

In-memory rate limiter разделён по Telegram user ID. Он достаточен только для одного
процесса и сбрасывается при перезапуске. До платного AI нужны персистентные дневные
лимиты, общий budget guard, блокировка пользователей и алерты расходов.

В логах допустимы user ID, material UUID, source type, status и безопасный error code.
Нельзя логировать token, database URL, полный Update, пользовательский текст или URL
с query. Пользователь получает только безопасные сообщения без SQL/driver details.

## Как расширять

- Новая команда: добавить отдельный handler в `entrypoints/bot.py`; бизнес-операцию
  оформить в application service.
- Новый вид источника: расширить `SourceType`, DB check constraint новой миграцией,
  классификатор и тесты.
- Новое поле материала: domain model → ORM row → mapping → repository protocol и
  adapter → Alembic migration → fake repository и тесты.
- AI-processing: читать pending attempts отдельным application use case/worker. Не
  помещать provider SDK, скачивание, SQL или транзакции в Telegram handlers.
- Несколько процессов: заменить in-memory limiter общим хранилищем и обеспечить
  единственного polling consumer либо перейти на webhook-инфраструктуру.

После изменения запускать `make check` и `make test`. Для схемы дополнительно
прогонять integration-тесты на отдельной PostgreSQL базе и вручную проверять двух
Telegram-пользователей по сценарию из ТЗ.
