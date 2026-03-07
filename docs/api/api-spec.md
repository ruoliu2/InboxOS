# API Spec

Base URL: `http://localhost:8000`

These endpoints match the current frontend implementation.

## Health

- `GET /health`

Returns a simple API heartbeat payload.

## Auth

### `GET /auth/google/start`

Starts the Google OAuth flow.

Query params:

- `redirect_to`
  - optional relative path to open after a successful sign-in
  - defaults to `/mail`

Response shape:

```json
{
  "provider": "google",
  "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
  "state": "opaque-oauth-state"
}
```

### `GET /auth/google/callback`

Completes the Google OAuth flow.

Query params:

- `code`
- `state`

Behavior:

- validates the saved OAuth state
- exchanges the code for Google tokens
- stores the session in the auth session database
- sets the HTTP-only session cookie
- returns `303 See Other` to the requested app route

### `GET /auth/session`

Returns the current authenticated session if the cookie is valid.

Response shape:

```json
{
  "authenticated": true,
  "provider": "google",
  "account_email": "user@example.com",
  "account_name": "User Name",
  "account_picture": "https://..."
}
```

If no valid session exists, the response is:

```json
{
  "authenticated": false
}
```

### `POST /auth/logout`

Deletes the current session and clears the session cookie.

Returns `204 No Content`.

## Gmail

The current live mail surface is provider-specific and uses `/gmail/*`.
This is the first shipped mail integration. Higher-level product docs stay
provider-agnostic, but the concrete API contract is Gmail-backed today.
Broader mail provider support may add additional adapters or route surfaces
later.

### `GET /gmail/threads`

Returns a paginated page of thread summaries.

Query params:

- `page_token`
  - optional Gmail page cursor returned by the previous response
- `page_size`
  - optional page size
  - defaults to `20`
  - minimum `1`, maximum `50`
- `q`
  - optional Gmail search query
  - accepted by the backend for provider-side search
  - the current web UI still filters only already-loaded summaries locally

Response shape:

```json
{
  "threads": [
    {
      "id": "thread_123",
      "subject": "Project update",
      "snippet": "Latest note from the thread",
      "participants": ["alice@example.com", "me@example.com"],
      "last_message_at": "2026-03-06T20:15:00Z",
      "action_states": ["to_reply"]
    }
  ],
  "next_page_token": "gmail-page-token",
  "has_more": true
}
```

Behavior:

- first page may be served from the persisted Gmail mailbox cache
- the backend refreshes the first page cache in the background
- summary pages contain lightweight thread metadata only

### `GET /gmail/threads/{thread_id}`

Returns the full thread detail for the selected Gmail thread.

Response shape:

```json
{
  "id": "thread_123",
  "subject": "Project update",
  "snippet": "Latest note from the thread",
  "participants": ["alice@example.com", "me@example.com"],
  "last_message_at": "2026-03-06T20:15:00Z",
  "action_states": ["to_reply"],
  "messages": [
    {
      "id": "msg_1",
      "sender": "alice@example.com",
      "sent_at": "2026-03-06T18:00:00Z",
      "body": "Could you send the revised deck?"
    }
  ],
  "analysis": null
}
```

Behavior:

- fetches the full Gmail thread on demand
- stores the returned detail in the persisted mailbox cache

### `POST /gmail/threads/{thread_id}/reply`

Sends a reply to the selected Gmail thread.

Request body:

```json
{
  "body": "Thanks, I will send the requested details this afternoon.",
  "mute_thread": true
}
```

Response shape:

```json
{
  "thread": {
    "id": "thread_123",
    "subject": "Project update",
    "snippet": "Thanks, I will send the requested details this afternoon.",
    "participants": ["alice@example.com", "me@example.com"],
    "last_message_at": "2026-03-06T20:45:00Z",
    "action_states": ["fyi"],
    "messages": [],
    "analysis": null
  },
  "sent_message": {
    "id": "msg_2",
    "sender": "me@example.com",
    "sent_at": "2026-03-06T20:45:00Z",
    "body": "Thanks, I will send the requested details this afternoon."
  },
  "muted": true
}
```

Behavior:

- sends the reply through Gmail
- re-fetches the updated thread
- persists the updated thread detail in the mailbox cache

## Calendar

### `GET /calendar/events`

Returns primary Google Calendar events for the authenticated account.

Query params:

- `time_min`
  - optional RFC 3339 start timestamp
  - defaults to 14 days before the request time
- `time_max`
  - optional RFC 3339 end timestamp
  - defaults to 60 days after the request time

## Tasks

### `GET /tasks`

Returns the current task list.

### `POST /tasks/create`

Creates a task.

Request body:

```json
{
  "title": "Send revised deck",
  "due_at": "2026-03-07T18:00:00Z",
  "thread_id": "thread_123",
  "category": "deadline"
}
```

### `POST /tasks/{task_id}/complete`

Marks a task as completed.

## Error Behavior

- `401 Unauthorized`
  - returned when the auth session is missing or expired
  - the web client redirects the user back to `/auth`
- `503 Service Unavailable`
  - returned for actionable Google configuration problems such as disabled Gmail or Calendar APIs
- `502 Bad Gateway`
  - returned for other upstream Google API failures or unexpected integration errors

## Notes

- auth sessions and OAuth state are persisted in SQLite at `SESSION_DB_PATH`
- Gmail thread summary pages and opened thread detail are persisted in SQLite at `GMAIL_CACHE_DB_PATH`
- task data is still stored in-memory and resets when the API process restarts
