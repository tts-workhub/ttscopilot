# TTS Copilot Backend

## Setup
1. Copy .env.example to .env and fill values.
2. docker-compose up -d
3. alembic upgrade head (migrations run)
4. uvicorn app.main:app --reload (dev)

## Migrations
alembic revision --autogenerate -m "initial"
alembic upgrade head