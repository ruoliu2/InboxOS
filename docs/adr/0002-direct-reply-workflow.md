# ADR 0002: Direct Reply Workflow

## Status

Accepted

## Decision

The mail workspace uses a direct thread reply endpoint instead of a separate review-oriented send flow.

## Why

- it aligns with the current mail UI
- it keeps the live contract smaller and easier to reason about
- it lets the backend return the updated thread state directly after reply

## Consequences

- the frontend sends replies through `POST /gmail/threads/{thread_id}/reply`
- the backend updates the thread in place and returns the updated thread payload
- thread reply remains a core part of the mail workspace contract
