.PHONY: setup check test db-upgrade db-downgrade api bot

VENV := .venv/bin

setup:
	uv sync --locked
check:
	$(VENV)/ruff check --no-cache .
	$(VENV)/ruff format --check --no-cache .
test:
	PYTHONDONTWRITEBYTECODE=1 $(VENV)/pytest -q -p no:cacheprovider
db-upgrade:
	$(VENV)/alembic upgrade head
db-downgrade:
	$(VENV)/alembic downgrade -1
api:
	$(VENV)/uvicorn linksift.entrypoints.api:app --reload
bot:
	$(VENV)/python -m linksift.entrypoints.bot
