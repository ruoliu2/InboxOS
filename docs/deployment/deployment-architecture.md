# Deployment Architecture

This document captures the intended deployment shape for the current MVP.

## Release Branch

- deploy branch: `codex/deploy-vercel-railway`
- deploy worktree: a sibling directory to the main repo checkout
- update flow: fetch `origin/main`, merge it into `codex/deploy-vercel-railway` from the deploy worktree, then push

## Hosting Plan

### Web

Platform: Vercel

Expected settings:

- production branch: `codex/deploy-vercel-railway`
- project root: `apps/web`
- build command: `bun run build`
- start command: `bun run start`
- enable source files outside the root directory because the app imports from `packages/*`
- env: `NEXT_PUBLIC_API_BASE_URL`
- env: `NEXT_PUBLIC_SESSION_COOKIE_NAME`

### API

Platform: Railway

Expected settings:

- production branch: `codex/deploy-vercel-railway`
- service root: `apps/api`
- port: `8000`
- deploy with `apps/api/Dockerfile`
- set `DATABASE_URL` to the Supabase production Postgres connection string
- set `CREDENTIAL_ENCRYPTION_KEY` for provider token encryption
- attach a persistent volume at `/data` only if Gmail cache should survive restarts
- env vars from `.env.example` plus production overrides for cookie security, allowed origins, and OAuth callback URLs
- public networking enabled with a Railway-provided domain

### Database

Platform: Supabase

Expected settings:

- one production Supabase project
- use Supabase local Docker through the CLI for local development
- use `docker compose up --build` only for local all-in-one startup
- keep schema migrations in `supabase/migrations`
- Railway is the only deployed service that receives the Supabase database connection string

### Desktop

Platform: not deployed yet

Current expectation:

- local macOS packaging only after the shared app packages are stable
- no production desktop deployment target during the current MVP phase

## Local Development

### Backend

```bash
supabase start

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

`docker-compose.yml` is local-only. It starts the web app, API, and a Compose-managed Postgres instance seeded from `supabase/migrations`. It does not affect Railway or Vercel deployment settings.

## Constraints

- auth, tasks, linked accounts, and conversation state persist in Supabase
- Gmail cache is still optional local disk state
- calendar has no backend service yet
- auth is not enforced app-wide yet
- future macOS packaging comes after the shared web surface is stable

See [vercel-railway-runbook.md](./vercel-railway-runbook.md) for the provider setup sequence and production environment contract.
