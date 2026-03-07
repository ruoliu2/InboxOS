.PHONY: api-dev web-dev desktop-dev dev api-test api-lint api-format web-lint web-format web-build format install-hooks up down

api-dev:
	cd apps/api && uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

web-dev:
	cd apps/web && bun run dev

desktop-dev:
	cd apps/desktop && bun run dev

dev:
	@echo "Run in separate terminals: make api-dev and make web-dev"

api-test:
	cd apps/api && uv run --group dev python -m pytest

api-lint:
	cd apps/api && uv run --group dev python -m ruff check

api-format:
	cd apps/api && uv run --group dev python -m ruff format . && uv run --group dev python -m ruff check --fix .

web-lint:
	cd apps/web && bun run lint

web-format:
	cd apps/web && bun run format

format:
	uvx pre-commit run --all-files

install-hooks:
	uvx pre-commit install --install-hooks

web-build:
	cd apps/web && bun run build

up:
	docker compose up --build

down:
	docker compose down
