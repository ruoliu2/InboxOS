# Deployment Architecture

This document captures the intended deployment shape for the current MVP.

## Hosting Plan

### Web

Platform: Vercel

Expected settings:

- project root: `apps/web`
- build command: `bun run build`
- start command: `bun run start`
- env: `NEXT_PUBLIC_API_BASE_URL`

### API

Platform: Railway

Expected settings:

- service root: `apps/api`
- port: `8000`
- deploy with `apps/api/Dockerfile` or native Python build
- env vars from `.env.example`

### Desktop

Platform: not deployed yet

Current expectation:

- local macOS packaging only after the shared app packages are stable
- no production desktop deployment target during the current MVP phase

## Local Development

### Backend

```bash
cd apps/api
uv sync --group dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd apps/web
bun install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 bun run dev
```

### Full Stack With Docker

```bash
docker compose up --build
```

## Constraints

- backend state is in-memory only
- calendar has no backend service yet
- auth is not enforced app-wide yet
- future macOS packaging comes after the shared web surface is stable
