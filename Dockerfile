FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN python -m pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["investment-monitor-web", "--host", "0.0.0.0", "--port", "8765", "--project-root", "/app"]
