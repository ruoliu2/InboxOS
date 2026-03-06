# API Spec

Base URL: `http://localhost:8000`

These endpoints match the current frontend implementation.

## Health

- `GET /health`

## Auth

- `GET /auth/google/start`
- `GET /auth/google/callback?code=...`

## Sync

- `POST /sync/start`
- `GET /sync/status`

Notes:

- sync uses the stub mail adapter in local development
- sync analyzes imported threads and creates deadline tasks

## Threads

- `GET /threads`
- `GET /threads?action_state=to_reply`
- `GET /threads/{thread_id}`
- `POST /threads/{thread_id}/analyze`
- `POST /threads/{thread_id}/reply`

Reply request body:

```json
{
  "body": "Thanks, I will send the requested details this afternoon.",
  "mute_thread": true
}
```

Reply behavior:

- appends an outbound message to the thread
- updates `snippet` and `last_message_at`
- moves the thread to `fyi`
- returns the updated `thread` plus `sent_message`

## Tasks

- `GET /tasks`
- `POST /tasks/create`
- `POST /tasks/{task_id}/complete`

## Notes

- current API is in-memory only
- task and thread state reset between process restarts
