.PHONY: setup lint type test docker-up docker-down

setup:
	uv sync --all-extras

lint:
	uv run ruff check .
	uv run ruff format --check .

type:
	uv run mypy

test:
	uv run python packages/core/test_evaluator.py
	uv run pytest

docker-up:
	docker compose -f infra/docker-compose.yml up -d

docker-down:
	docker compose -f infra/docker-compose.yml down
