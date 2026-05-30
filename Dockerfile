FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY toolrampart ./toolrampart
COPY examples ./examples

RUN pip install --no-cache-dir ".[postgres,redis,otel]"

EXPOSE 8000

CMD ["toolrampart", "serve", "--host", "0.0.0.0", "--port", "8000"]
