.PHONY: install dev dev-sse lint format test typecheck clean docker-build

install:
	uv sync

dev:
	uv run python -m aismartbuddy --transport stdio

dev-sse:
	uv run python -m aismartbuddy --transport sse --port 8000

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

test:
	uv run pytest -v

typecheck:
	uv run pyright

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf dist/ *.egg-info

docker-build:
	docker build -t aismartbuddy .
