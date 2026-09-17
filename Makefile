.PHONY: setup check test api bot

VENV := .venv/bin

setup:
	uv sync --locked
check:
	$(VENV)/ruff check --no-cache .
	$(VENV)/ruff format --check --no-cache .
test:
	PYTHONDONTWRITEBYTECODE=1 $(VENV)/pytest -q -p no:cacheprovider
api:
	$(VENV)/uvicorn linksift.entrypoints.api:app --reload
bot:
	$(VENV)/python -m linksift.entrypoints.bot
