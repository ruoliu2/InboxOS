# Backend Design

Backend root: `apps/api/`

## Framework And App Wiring

- FastAPI app entry: `apps/api/app/main.py`
- router exports: `apps/api/app/routers/`
- dependency wiring: `apps/api/app/services/dependencies.py`
- in-memory state for sessions, tasks, legacy threads, and sync: `apps/api/app/storage/store.py`
- persisted cache for the current Gmail provider: `apps/api/app/storage/mailbox_cache.py`

## Active Routes

### Health

- `GET /health`

### Auth

- `GET /auth/google/start`
- `GET /auth/google/callback`
- `GET /auth/session`
- `POST /auth/logout`

### Gmail

- `GET /gmail/threads`
- `GET /gmail/threads/{thread_id}`
- `POST /gmail/threads/{thread_id}/reply`

These are the provider-specific routes for the first shipped mail integration.

### Calendar

- `GET /calendar/events`

### Legacy Sync And Threads

- `POST /sync/start`
- `GET /sync/status`

- `GET /threads`
- `GET /threads/{thread_id}`
- `POST /threads/{thread_id}/analyze`
- `POST /threads/{thread_id}/reply`

### Tasks

- `GET /tasks`
- `POST /tasks/create`
- `POST /tasks/{task_id}/complete`

## Service Boundaries

### `ThreadService`

File: `apps/api/app/services/thread_service.py`

Responsibilities:

- list legacy in-memory threads
- return legacy thread detail
- analyze a thread through the LLM adapter
- send direct replies and mutate thread state after reply

### `TaskService`

File: `apps/api/app/services/task_service.py`

Responsibilities:

- list tasks
- create tasks directly
- complete tasks
- create deadline tasks from analyzed thread data

### `SyncService`

File: `apps/api/app/services/sync_service.py`

Responsibilities:

- call the stub mail adapter
- store imported legacy threads
- analyze each synced thread
- create tasks derived from deadlines
- update in-memory sync status state

### `AuthService`

File: `apps/api/app/services/auth_service.py`

Responsibilities:

- provide Google auth start and callback behavior for the auth surface
- store and refresh authenticated sessions behind the session cookie
- expose current session state and logout behavior

### Mail integration layer

Files:

- `apps/api/app/routers/gmail.py`
- `apps/api/app/integrations/google_workspace.py`

Responsibilities:

- expose the current live mailbox routes
- keep the backend mail path ready for additional providers later
- keep provider-specific concerns behind the live mail route surface

### `GoogleWorkspaceClient`

File: `apps/api/app/integrations/google_workspace.py`

Responsibilities:

- act as the current concrete Gmail provider behind the mail integration layer
- build Google OAuth URLs and exchange auth codes for tokens
- refresh expired Google access tokens when a refresh token is available
- list Gmail inbox thread summaries with pagination
- fetch full Gmail thread detail and send Gmail replies
- fetch Google Calendar events
- turn Google service-disabled failures into actionable app errors

### `GmailMailboxCache`

File: `apps/api/app/storage/mailbox_cache.py`

Responsibilities:

- store Gmail thread summaries for the current provider by account, query, and page token
- store Gmail thread detail by account and thread id
- serve cached first-page inbox summaries before a background refresh
- keep mailbox cache state separate from the in-memory demo store

## Integration Boundaries

### Google Workspace APIs

File: `apps/api/app/integrations/google_workspace.py`

Current behavior:

- current concrete implementation behind the provider-ready mail integration layer
- Gmail is the first live mail provider
- future providers are intended to plug into the same mail integration layer later
- uses Gmail API for inbox summaries, thread detail, and replies
- uses Google Calendar API for the calendar workspace
- requires Google OAuth client configuration plus enabled Gmail and Calendar APIs

### Mail Adapter

File: `apps/api/app/integrations/mail/mailcore_adapter.py`

Current behavior:

- returns deterministic stub thread data for local development
- acts as the inbox source for the legacy sync path only

### LLM Adapter

Files:

- `apps/api/app/integrations/llm/base.py`
- `apps/api/app/integrations/llm/openai_compatible.py`

Current behavior:

- heuristic analysis only
- extracts summary, requested items, deadlines, and action states
- no remote LLM call in the MVP stub path
