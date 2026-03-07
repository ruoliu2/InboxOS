# InboxOS MVP

InboxOS is a mail-first AI workspace with one shared UI direction across the live web app and a planned macOS desktop shell.

## Monorepo Layout

- `apps/web`: Next.js host app for the current product surface
- `apps/desktop`: planned macOS desktop shell around the shared app packages
- `apps/api`: FastAPI backend for auth, mail, calendar, sync, threads, and tasks
- `packages/app`: shared app shell and route-level page composition
- `packages/features`: mail, tasks, calendar, and auth feature workspaces
- `packages/ui`: shared UI chrome such as the left app rail
- `packages/lib`: shared API client, formatters, and mock data
- `packages/types`: shared TypeScript models
- `packages/config`: shared client-side configuration
- `docs`: product and technical documentation
- `ui`: local ignored checkout of upstream `shadcn/ui` for reference only

## Architecture

```mermaid
graph TD
A1["Browser user"] --> B1["Apps web"]
A2["Desktop user"] --> C1["Apps desktop"]
B1 --> D1["Shared app packages"]
C1 --> D1
D1 --> E1["Apps api"]
E1 --> F1["Mail integration layer"]
F1 --> G1["Mailbox cache"]
E1 --> H1["Auth and calendar integration"]
E1 --> I1["Action engine"]
I1 --> J1["Task service"]
E1 --> K1["Reply workflow"]
```

## Core Flows

```mermaid
graph TD
A1["Connect mail account"] --> B1["Load thread summaries"]
B1 --> C1["Open thread detail on demand"]
B1 --> D1["Scroll for older inbox pages"]
C1 --> E1["User sends direct reply"]
E1 --> F1["Thread refreshes in place"]
```

## Local Development

### Prereqs

- Python 3.11+
- `uv`
- Node 20+
- `bun`
- Docker optional

### Backend

```bash
cp .env.example .env
# Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI in .env.
# Enable Gmail API and Google Calendar API in the same Google Cloud project.
# Optionally set GMAIL_CACHE_DB_PATH to move the persisted Gmail mailbox cache.

cd apps/api
uv sync --group dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Web

```bash
cd apps/web
bun install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 bun run dev
```

Open [http://localhost:3000/mail](http://localhost:3000/mail).

## Mail Workspace Behavior

- first mailbox paint loads the newest 20 thread summaries
- full thread detail loads only when a thread is opened or deep-linked
- scrolling near the bottom loads older inbox pages
- search currently filters only the summaries already loaded in the client
- the current live mail integration uses Gmail, and the backend persists summary pages and opened thread detail in a local cache by default at `~/.cache/inboxos/gmail_mailbox_cache.sqlite3`

### Desktop

`apps/desktop` is a shell scaffold only. It exists to keep the repo aligned with the future macOS-compatible packaging plan, but the web app remains the active runtime today.

### Git Hooks

Enable the versioned pre-commit hooks once per clone:

```bash
make install-hooks
```

The repo uses the Python `pre-commit` package. Hooks run `black` and `ruff` on `apps/api`, and `prettier` across the tracked JS, TS, CSS, JSON, and Markdown files in `apps/`, `packages/`, and `docs/`.

To run the same checks manually across the repo:

```bash
uvx pre-commit run --all-files
```

## Test And Lint

```bash
cd apps/api
uv run --group dev ruff check
uv run --group dev python -m pytest

cd ../web
bun run lint
bun run build
```

## Docker Compose

```bash
docker compose up --build
```

- API: [http://localhost:8000](http://localhost:8000)
- Web: [http://localhost:3000](http://localhost:3000)

## Deploy

### Web on Vercel

- project root: `apps/web`
- build command: `bun run build`
- start command: `bun run start`
- env: `NEXT_PUBLIC_API_BASE_URL`

### API on Railway

- service root: `apps/api`
- deploy with `apps/api/Dockerfile` or native Python build
- expose port `8000`
- set env vars from `.env.example`
- optionally set `GMAIL_CACHE_DB_PATH` if the deploy target provides persistent storage for the mailbox cache

## Current MVP Status

Implemented:

- mail-first shared UI structure for web and future desktop shell reuse
- Google-backed auth start, callback, session, and logout flow with an HTTP-only session cookie
- the live mail integration currently uses Gmail with summary-first inbox loading and a persisted first-page cache
- full thread fetch on open plus direct reply from the mail workspace
- infinite scroll for older inbox pages
- Google Calendar event loading in the calendar workspace
- mail, tasks, calendar, and auth surfaces in the web host app
- legacy in-memory `/threads` and `/sync` flows remain available for thread analysis and task demos
