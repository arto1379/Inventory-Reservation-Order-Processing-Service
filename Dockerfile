# Single image reused for the API, the Celery worker, Celery Beat, and the
# outbox relay process (docker-compose just points each service at a
# different startup command). Keeping one image avoids duplicated dependency
# installs and keeps all processes running identical application code.
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr so logs
# show up immediately in `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps needed to build psycopg2 / bcrypt wheels on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Default command: run the API. docker-compose.yml overrides this for the
# worker / beat / outbox-relay services.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
