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

### `ThreadSummaryPage`

Fields:

- `threads`
- `next_page_token`
- `has_more`

### `ThreadAnalysis`

Fields:

- `summary`
- `action_items`
- `deadlines`
  - array of `ExtractedDeadline`
- `extracted_tasks`
  - array of `ExtractedTask`
- `requested_items`
- `recommended_next_action`
- `action_states`
- `analyzed_at`

### `ExtractedDeadline`

Fields:

- `title`
- `due_at`
- `source_message_id`
- `is_date_only`

### `ExtractedTask`

Fields:

- `title`
- `category`
- `due_at`
- `deadline_source`
- `source_message_id`

### `ThreadDetail`

`ThreadDetail` extends `ThreadSummary` with:

- `messages`
- `analysis`

### `ReplyToThreadRequest`

Fields:

- `body`
- `mute_thread`

### `ReplyToThreadResponse`

Fields:

- `thread`
- `sent_message`
- `muted`

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
- `origin`
- `origin_key`
- `deadline_source`
- `created_at`
- `completed_at`

## Auth Models

### `AuthStartResponse`

Fields:

- `provider`
- `authorization_url`
- `state`

### `AuthSessionResponse`

Fields:

- `authenticated`
- `provider`
- `account_email`
- `account_name`
- `account_picture`

## Storage Model

The current backend store keeps:

- tasks
- auth sessions and OAuth state in SQLite at `SESSION_DB_PATH`
- Gmail thread summary pages and opened thread detail in SQLite at `GMAIL_CACHE_DB_PATH`
- persisted conversations and conversation insights in the app database

Task data is now persisted in the app database instead of in-memory only.
