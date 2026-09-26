# Crewly

Crewly is the agent that finds, manages, and creates collaboration opportunities for electric utilities. It helps teams coordinate planned work, estimate shared savings, and respond to active weather and storm conditions. It combines utility filing data, geographic and grid layers, restoration plans, live feeds, and an operations interface for reviewing opportunities and preparing outreach.

## Stack

- Backend: Python 3.12, FastAPI, PostgreSQL with TimescaleDB, and `uv`
- Frontend: React, TypeScript, Vite, Tailwind CSS, and MapLibre
- Database: PostgreSQL on port `5433` when run with the included Compose file

## Requirements

- Python 3.12+
- Node.js 22+
- `uv`
- Docker, for the local database

## Local setup

From the repository root:

```sh
cp .env.example .env
docker compose up -d db
```

Install the backend and frontend dependencies:

```sh
cd backend
uv sync
cd ../frontend
npm ci
```

Initialize the database and load the development data. The build downloads and processes external geographic, filing, weather, and storm data, so it can take some time and may require the relevant API keys in `.env`.

```sh
cd backend
uv run python -m scripts.build_all
```

Start the backend in one terminal:

```sh
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

Start the frontend in another:

```sh
cd frontend
npm run dev
```

Vite serves the frontend and proxies `/api` requests to `http://localhost:8000`. Set `API_URL` when the backend runs elsewhere.

## Environment

`.env.example` lists the available settings. `DATABASE_URL` defaults to:

```text
postgresql://postgres:opencrew@localhost:5433/opencrew
```

The external-data and outreach integrations use `GEMINI_API_KEY`, `GOOGLE_PLACES_KEY`, and `RESEND_API_KEY` when those features are enabled. The local LLM settings and demo inbox values are optional.

## Tests and checks

Backend tests:

```sh
cd backend
uv run pytest
```

Frontend type-check and production build:

```sh
cd frontend
npm run build
```

## Production image

The included `Dockerfile` builds the frontend and packages it with the FastAPI service. It expects `PORT` and the database and integration environment variables at runtime.
