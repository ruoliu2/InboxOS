# Backend Design

Backend root: `apps/api/`

## Framework And App Wiring

- FastAPI app entry: `apps/api/app/main.py`
- router exports: `apps/api/app/routers/`
- dependency wiring: `apps/api/app/services/dependencies.py`
- in-memory task state: `apps/api/app/storage/store.py`
- persisted auth state: `apps/api/app/storage/auth_store.py`
- persisted mailbox cache: `apps/api/app/storage/mailbox_cache.py`

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

### Tasks

- `GET /tasks`
- `POST /tasks/create`
- `POST /tasks/{task_id}/complete`

## Service Boundaries

### `AuthService`

File: `apps/api/app/services/auth_service.py`

Responsibilities:

- provide Google auth start and callback behavior
- restore and refresh persisted sessions
- clear auth state on logout

### `TaskService`

File: `apps/api/app/services/task_service.py`

Responsibilities:

- list tasks
- create tasks directly
- complete tasks

### Mail integration layer

Files:

- `apps/api/app/routers/gmail.py`
- `apps/api/app/integrations/google_workspace.py`
- `apps/api/app/storage/mailbox_cache.py`

Responsibilities:

- list Gmail thread summaries with pagination
- fetch full Gmail thread detail on demand
- send Gmail replies
- read from and write to the persisted mailbox cache

### `GoogleWorkspaceClient`

File: `apps/api/app/integrations/google_workspace.py`

Responsibilities:

- build Google auth URLs
- exchange and refresh Google OAuth tokens
- load Gmail thread summaries and full thread detail
- send Gmail replies
- load Google Calendar events
- turn Google service-disabled failures into actionable app errors

## Integration Boundaries

### Google Workspace APIs

Used for:

- Google OAuth sign-in
- Gmail inbox summary pages
- Gmail full thread reads
- Gmail reply send
- Google Calendar event reads

## Storage Notes

- tasks remain in-memory for the current MVP
- auth sessions and pending OAuth state are persisted in SQLite
- Gmail summary pages and opened thread detail are persisted in SQLite
- the removed legacy demo mail stack no longer exists in app wiring
