# Crewly

Crewly is an agentic operations platform for discovering, evaluating, and coordinating high-value collaboration opportunities across organizations. It turns fragmented plans, operational data, geographic context, and live conditions into actionable recommendations, shared work plans, and stakeholder outreach. The current application brings together utility filings, grid and geographic layers, restoration plans, weather and storm feeds, and the workflows needed to review and act on each opportunity.

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
