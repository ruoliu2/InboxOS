# System Context

This document explains the current product boundary and runtime shape.

## Product Surface

InboxOS currently centers on four app surfaces:

- mail
- tasks
- calendar
- auth

The primary entry route remains `/mail`.

## System Context

```mermaid
graph TD
A1["User in browser"] --> B1["Apps web"]
A2["User in desktop shell"] --> C1["Apps desktop"]
B1 --> D1["Shared app packages"]
C1 --> D1
D1 --> E1["Apps api"]
E1 --> F1["Mail sync adapter"]
E1 --> G1["Analysis engine"]
G1 --> H1["Task generation"]
E1 --> I1["Reply workflow"]
```

## Responsibilities

### `apps/web`

The web host owns:

- the live Next.js runtime
- route entry points under `apps/web/app`
- global CSS and metadata for the current production surface

### `apps/desktop`

The desktop app owns:

- the future macOS shell around the shared UI packages
- preload and runtime integration points for desktop-specific APIs
- packaging concerns separate from the shared UI logic

### `packages/`

The shared packages own:

- app shell composition
- mail, tasks, calendar, and auth screens
- shared UI chrome
- shared API client, types, mock data, and config

### `apps/api`

The API owns:

- thread sync
- thread analysis
- direct thread reply mutation
- task creation and completion
- auth start and callback endpoints

## Delivery Plan

The current hosting plan is:

- Vercel for `apps/web`
- Railway for `apps/api`
- local-only packaging work for `apps/desktop` until the shared UI is stable
