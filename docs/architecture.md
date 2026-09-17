# Архитектура LinkSift

Статус: стартовый каркас личного MVP. Приложение — модульный монолит на Python,
который локально запускается из `.venv` одним процессом Telegram-бота. FastAPI
остаётся отдельной необязательной точкой входа для health check и будущего webhook.

```text
Telegram → aiogram bot → application use case
                            ↓
                 MaterialRepository
                            ↓
               SQLAlchemy → Supabase PostgreSQL
                            ↓
                     media pipeline
                    ↙              ↘
             Gemini video     ffmpeg → ASR/OCR → LLM
                    ↘              ↙
                validation → formatter → Telegram
```

## Слои и границы

- `domain/`: контракты результата, evidence и контекста без SDK и ввода-вывода;
- `application/`: интерфейсы провайдеров и `MaterialRepository` без зависимостей
  от SQLAlchemy, Psycopg, Supabase SDK, Telegram или FastAPI;
- `entrypoints/`: тонкие точки входа bot и API;
- `infrastructure/database/`: асинхронный SQLAlchemy/Psycopg adapter для PostgreSQL;
- будущие infrastructure adapters: downloader, ffmpeg и AI SDK.

Зависимости направлены к `domain` и `application`. Telegram handlers не должны
содержать анализ медиа. Провайдеры реализуют Protocol и выбираются конфигурацией.

## Выполнение задач

На первом этапе запрос обрабатывается в процессе бота через внутреннюю ограниченную
`asyncio.Queue`. Один consumer последовательно выполняет тяжёлые задачи, а bot loop
продолжает принимать сообщения. Состояние и результат сохраняются в PostgreSQL до и
после обработки. После аварийного перезапуска незавершённые записи переводятся в
повторяемое состояние по явной политике.

Это решение рассчитано на одного владельца и около 10 материалов в день. Оно не
обеспечивает распределённую обработку. При появлении нескольких worker-процессов,
VPS или требований к надёжной фоновой доставке очередь заменяется на Redis/Arq
либо другой broker без изменения domain-контрактов.

## Хранение

Supabase PostgreSQL — единственный постоянный источник данных. Таблицы `materials`,
`processing_attempts` и `analysis_results` создаются Alembic-миграцией. ORM-модели
отделены от Pydantic-моделей предметной области. Каждая repository-операция создаёт
собственную async session и транзакцию; глобальной session нет.

Все запросы к материалу включают `owner_telegram_id`. Активные материалы уникальны
по владельцу и нормализованному `source_key`; после soft delete тот же источник
можно добавить снова. Повторный анализ создаёт отдельную попытку. Результат проходит
Pydantic-валидацию перед записью в JSONB. RLS включён без публичных policies, поэтому
таблицы недоступны через Supabase Data API и используются только backend-подключением.

## Pipeline

При доступном легальном аккаунте Gemini — основной video provider. Локальные
ASR/OCR и текстовая LLM — резервный pipeline. Конкретные модели и тяжёлые зависимости
Whisper/Paddle подключаются после spike и проверки Mac/VPS. Имена, цены и preview-
возможности из ТЗ перед интеграцией перепроверяются.

Временные сетевые ошибки допускают ограниченный retry с backoff. Ошибки авторизации
и постоянной квоты не повторяются. Fallback включается только по определённой
политике времени и стоимости.

Контракт запрещает лишние поля, отрицательные таймкоды, confidence вне `[0,1]` и
`confirmed` без evidence. Это структурная проверка; отдельный validator должен
сверять evidence с исходником и внешними каталогами.

## Безопасность и жизненный цикл

Allowlist применяется ко всем Telegram updates. Перед включением скачиваний нужны:
проверка URL, DNS и каждого redirect от SSRF; запрет внутренних сетей и metadata
endpoints; streaming-лимиты, timeouts, `ffprobe`, subprocess без shell и случайные
имена временных файлов.

Медиа удаляется в `finally` и периодическим TTL sweeper после аварий. Загруженные
провайдеру файлы также удаляются. URL с секретами, Telegram updates и credentials
не логируются.

## Порядок реализации

1. Spike Gemini и локального fallback на 20–30 реальных материалах.
2. PostgreSQL schema, migrations, repository, статусы и idempotency. **Готово.**
3. Приём Telegram-файла, лимиты, `asyncio.Queue`, orchestration и TTL cleanup.
4. Один рабочий AI pipeline, evidence validator, formatter и отправка ответа.
5. Безопасные URL adapters и ручной upload fallback.
6. ASR/OCR fallback, экспорт, повторный анализ, удаление и метрики.
7. Перед VPS оценить Docker и внешнюю очередь по фактической нагрузке.

Открыто: сервер/регион, credentials/model и поддержка статей в первом срезе.
Webhook и Obsidian отложены.
