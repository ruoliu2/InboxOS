# InboxOS API

FastAPI backend for InboxOS MVP.

## Local Setup

Run the API from the repo root so it can pick up the shared `.env` file.

Required Google settings:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`

Optional persisted state settings:

- `SESSION_DB_PATH`
  - defaults to `~/.cache/inboxos/auth_sessions.sqlite3`
- `GMAIL_CACHE_DB_PATH`
  - defaults to `~/.cache/inboxos/gmail_mailbox_cache.sqlite3`

Before calling the Gmail or Calendar routes, enable both the Gmail API and Google Calendar API in the same Google Cloud project as the OAuth client.

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
- `/gmail/threads`
- `/gmail/threads/{thread_id}`
- `/gmail/threads/{thread_id}/reply`
- `/calendar/events`
- `/tasks`
- `/tasks/create`
- `/tasks/{task_id}/complete`
