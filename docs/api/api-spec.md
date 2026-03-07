# API Spec

Base URL: `http://localhost:8000`

These endpoints match the current frontend implementation.

## Health

- `GET /health`

## Auth

- `GET /auth/google/start?redirect_to=/mail`
  - builds the Google OAuth URL and returns `{ provider, authorization_url, state }`
- `GET /auth/google/callback?code=...&state=...`
  - exchanges the authorization code, creates a server-side session, sets the session cookie, and redirects with `303 See Other`
- `GET /auth/session`
  - returns `{ "authenticated": false }` when the cookie is missing or invalid
  - returns `{ authenticated, provider, account_email, account_name, account_picture }` when the session is valid
- `POST /auth/logout`
  - clears the server-side session and deletes the session cookie

## Gmail

- `GET /gmail/threads`
- `GET /gmail/threads?page_size=20`
- `GET /gmail/threads?page_token=...`
- `GET /gmail/threads?q=from:alice newer_than:7d`
- `GET /gmail/threads/{thread_id}`
- `POST /gmail/threads/{thread_id}/reply`

`GET /gmail/threads` query params:

- `page_size`: defaults to `20`, minimum `1`, maximum `50`
- `page_token`: loads the next page of older inbox threads
- `q`: forwards Gmail-style query text to the Gmail API

Notes:

- these `/gmail/*` routes are the current provider-specific surface for the first shipped mail integration
- broader mail provider support may add additional adapters or endpoints later
- the Gmail list endpoint returns inbox summaries first and defers full thread bodies to `GET /gmail/threads/{thread_id}`
- the first page without `q` may be served from the persisted mailbox cache and refreshed in the background
- the current web UI still searches only the already loaded summaries in memory, even though the backend accepts `q`

`GET /gmail/threads` response shape:

```json
{
  "threads": [
    {
      "id": "thread_123",
      "subject": "Quarterly planning",
      "snippet": "Can you send the revised deck before Friday?",
      "participants": ["alice@example.com", "you@example.com"],
      "last_message_at": "2026-03-06T15:22:11Z",
      "action_states": ["to_reply"]
    }
  ],
  "next_page_token": "1890abc",
  "has_more": true
}
```

Reply request body:

```json
{
  "body": "Thanks, I will send the requested details this afternoon.",
  "mute_thread": true
}
```

Reply behavior:

- sends a Gmail reply in the selected thread
- refreshes the cached thread detail for the authenticated account
- returns the updated `thread`, the `sent_message`, and the `muted` flag

## Calendar

- `GET /calendar/events`
- `GET /calendar/events?time_min=2026-03-01T00:00:00Z&time_max=2026-05-01T00:00:00Z`

Notes:

- `time_min` defaults to 14 days in the past when omitted
- `time_max` defaults to 60 days in the future when omitted

## Legacy Thread And Sync Routes

- `POST /sync/start`
- `GET /sync/status`
- `GET /threads`
- `GET /threads?action_state=to_reply`
- `GET /threads/{thread_id}`
- `POST /threads/{thread_id}/analyze`
- `POST /threads/{thread_id}/reply`

Notes:

- these routes still exist for the in-memory demo and analysis flow
- they are separate from the live Gmail mailbox endpoints above
- sync still uses the stub mail adapter in local development

## Tasks

- `GET /tasks`
- `POST /tasks/create`
- `POST /tasks/{task_id}/complete`

## Error Behavior

- `401 Authentication required.` when a protected route is called without a valid auth session
- `503` with an actionable message when Google OAuth is not configured or Gmail or Calendar APIs are disabled for the configured Google project
- `502` for unexpected upstream Google or runtime failures

## Notes

- Gmail summary pages and opened thread details are persisted at `GMAIL_CACHE_DB_PATH`, which defaults to `~/.cache/inboxos/gmail_mailbox_cache.sqlite3`
- legacy task, thread, auth state, and sync status still live in memory and reset between process restarts
