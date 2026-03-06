# Schema

This document summarizes the key live data models in the current MVP.

## Enums

### `ActionState`

- `to_reply`
- `to_follow_up`
- `task`
- `fyi`

### `TaskStatus`

- `open`
- `completed`

### `SyncStatus`

- `idle`
- `running`
- `completed`
- `failed`

## Thread Models

### `ThreadMessage`

Fields:

- `id`
- `sender`
- `sent_at`
- `body`

### `ThreadSummary`

Fields:

- `id`
- `subject`
- `snippet`
- `participants`
- `last_message_at`
- `action_states`

### `ThreadAnalysis`

Fields:

- `summary`
- `action_items`
- `deadlines`
- `requested_items`
- `recommended_next_action`
- `action_states`
- `analyzed_at`

### `ThreadDetail`

`ThreadDetail` extends `ThreadSummary` with:

- `messages`
- `analysis`

## Task Models

### `CreateTaskRequest`

Fields:

- `title`
- `due_at`
- `thread_id`
- `category`

### `TaskItem`

Fields:

- `id`
- `title`
- `status`
- `due_at`
- `thread_id`
- `category`
- `created_at`
- `completed_at`

## Sync Models

### `SyncStartRequest`

Fields:

- `account_email`
- `force`

### `SyncStartResponse`

Fields:

- `sync_id`
- `status`
- `imported_threads`
- `started_at`

### `SyncStatusResponse`

Fields:

- `sync_id`
- `status`
- `imported_threads`
- `updated_at`
- `last_error`

## Auth Models

### `AuthStartResponse`

Fields:

- `provider`
- `authorization_url`
- `state`

### `AuthCallbackResponse`

Fields:

- `provider`
- `connected`
- `account_email`
- `message`

## Storage Model

The current backend store keeps:

- threads
- tasks
- sync status

The store is in-memory, so data resets when the backend process restarts.
