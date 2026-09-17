# Подключение Supabase PostgreSQL

LinkSift подключается к Supabase как обычный backend PostgreSQL через SQLAlchemy и
Psycopg. Supabase SDK, Project URL и anon key не используются.

## 1. Создать проект

1. Создать отдельный проект в [Supabase Dashboard](https://supabase.com/dashboard).
2. Сохранить database password. Если он потерян, задать новый в настройках базы.
3. Открыть проект и нажать **Connect** в верхней части Dashboard.
4. Выбрать **Session pooler** и скопировать URI с портом `5432`.

Нужен именно Session pooler, а не Direct connection, Transaction pooler, Project URL
или API key. Session pooler доступен по IPv4 и поддерживает обычные длительные
backend-соединения и prepared statements.

Официальные материалы: [подключение к PostgreSQL](https://supabase.com/docs/guides/database/connecting-to-postgres)
и [connection pooling](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits).

## 2. Добавить одну строку в `.env`

Supabase показывает строку примерно такого вида:

```text
postgresql://postgres.PROJECT_REF:[YOUR-PASSWORD]@POOLER_HOST:5432/postgres
```

Для LinkSift заменить только протокол `postgresql://` на
`postgresql+psycopg://`, подставить database password и добавить обязательный SSL:

```dotenv
LINKSIFT_DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

`PROJECT_REF`, имя пользователя и `POOLER_HOST` необходимо копировать из Connect:
pooler host нельзя надёжно составить вручную. Если пароль содержит `@`, `:`, `/`,
`?`, `#`, `%` или пробел, эти символы нужно percent-encode. Не отправлять реальную
строку подключения в чат и не добавлять её в документацию.

Файл `.env` уже исключён из Git. В `.env.example` остаётся только пустое значение.

## 3. Создать таблицы

Вручную вставлять SQL в Supabase SQL Editor не требуется. Из корня проекта выполнить:

```sh
make db-upgrade
```

Alembic применит миграцию `20260917_0001`, которая создаёт:

- `materials`;
- `processing_attempts`;
- `analysis_results`;
- UUID, foreign keys, JSONB, status checks и индексы;
- частичную уникальность активного `owner_telegram_id + source_key`;
- автоматическое обновление `materials.updated_at`;
- RLS без публичных policies.

Проверить применённую версию:

```sh
.venv/bin/alembic current
```

Откатить последнюю миграцию при необходимости:

```sh
make db-downgrade
```

Миграции не запускаются автоматически при импорте или старте приложения.

## Отдельная интеграционная база

Unit-тесты не подключаются к PostgreSQL. Для необязательных integration-тестов
создать отдельный Supabase project/database и задать только на время запуска:

```sh
LINKSIFT_TEST_DATABASE_URL="postgresql+psycopg://..." \
  .venv/bin/pytest -m integration
```

Integration-тесты никогда не подставляют `LINKSIFT_DATABASE_URL` автоматически и
отказываются запускаться, если test URL совпадает с основной базой.
