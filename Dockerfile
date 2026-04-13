FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN uv pip install --system .

CMD ["aismartbuddy", "--transport", "stdio"]
