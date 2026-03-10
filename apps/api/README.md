# InboxOS API

FastAPI backend for InboxOS MVP.

## Local Setup

Run the API from the repo root so it can pick up the shared `.env` file.

Required Google settings:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Optional callback setting:

- `GOOGLE_REDIRECT_URI`
  - defaults to `http://localhost:3000/api/gateway/auth/google/callback` locally
  - otherwise falls back to `WEB_BASE_URL + /api/gateway/auth/google/callback`
  - if `WEB_BASE_URL` is blank, Railway can still fall back to `RAILWAY_PUBLIC_DOMAIN`

Optional persisted state settings:

- `DATABASE_URL`
  - for local Supabase CLI, copy the value from `supabase status -o env`
  - use Supabase local Docker for development and your Supabase cloud Postgres connection string in production
- `CREDENTIAL_ENCRYPTION_KEY`
  - required in shared environments to encrypt provider access and refresh tokens
- `GMAIL_CACHE_DB_PATH`
  - defaults to `~/.cache/inboxos/gmail_mailbox_cache.sqlite3`

Local Supabase workflow:

```bash
brew install supabase/tap/supabase
supabase start
supabase db reset
```

The API expects Supabase local Postgres on `127.0.0.1:54322` unless `DATABASE_URL` is overridden.

Docker Compose workflow:

```bash
docker compose up --build
```

This Compose stack starts the API, web app, and a local Postgres container seeded from `supabase/migrations`. Do not run it at the same time as `supabase start`, because both flows bind local database port `54322`.

Before calling the Gmail or Calendar routes, enable both the Gmail API and Google Calendar API in the same Google Cloud project as the OAuth client.

For local Google OAuth, use:

- `WEB_BASE_URL=http://localhost:3000`
- `GOOGLE_REDIRECT_URI=http://localhost:3000/api/gateway/auth/google/callback`

Run local checks from this directory with:

```bash
uv sync --group dev
uv run --group dev ruff check
uv run --group dev python -m pytest
```

Primary live routes:

- `/auth/google/start`
- `/auth/google/callback`
- `/auth/session`
- `/auth/logout`
- `/accounts`
- `/accounts/{provider}/connect/start`
- `/accounts/{provider}/callback`
- `/accounts/{account_id}/disconnect`
- `/accounts/{account_id}/activate`
- `/gmail/threads`
- `/gmail/threads/{thread_id}`
- `/gmail/threads/{thread_id}/reply`
- `/calendar/events`
- `/tasks`
- `/tasks/create`
- `/tasks/{task_id}/complete`

The `/gmail/*` routes are provider-specific today because Gmail is the first
shipped mail integration. Higher-level product docs stay provider-agnostic.
