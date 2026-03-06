# Backend Design

Backend root: `apps/api/`

## Framework And App Wiring

- FastAPI app entry: `apps/api/app/main.py`
- router exports: `apps/api/app/routers/`
- dependency wiring: `apps/api/app/services/dependencies.py`
- in-memory state: `apps/api/app/storage/store.py`

## Active Routes

### Health

- `GET /health`

### Auth

- `GET /auth/google/start`
- `GET /auth/google/callback`

### Sync

- `POST /sync/start`
- `GET /sync/status`

### Threads

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

- list threads
- return thread detail
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

- call the mail adapter
- store imported threads
- analyze each synced thread
- create tasks derived from deadlines
- update sync status state

### `AuthService`

File: `apps/api/app/services/auth_service.py`

Responsibilities:

- provide Google auth start and callback behavior for the auth surface

## Integration Boundaries

### Mail Adapter

File: `apps/api/app/integrations/mail/mailcore_adapter.py`

Current behavior:

- returns deterministic stub thread data for local development
- acts as the inbox source for sync

### LLM Adapter

Files:

- `apps/api/app/integrations/llm/base.py`
- `apps/api/app/integrations/llm/openai_compatible.py`

Current behavior:

- heuristic analysis only
- extracts summary, requested items, deadlines, and action states
- no remote LLM call in the MVP stub path
