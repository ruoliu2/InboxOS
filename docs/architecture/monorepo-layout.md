# Monorepo Layout

This document describes the current repository layout and ownership boundaries.

## Top Level

```text
InboxOS/
├── apps/
│   ├── api/
│   ├── desktop/
│   └── web/
├── packages/
│   ├── app/
│   ├── config/
│   ├── features/
│   ├── lib/
│   ├── types/
│   └── ui/
├── docs/
├── ui/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
├── README.md
└── docker-compose.yml
```

## Ownership

### `apps/api/`

FastAPI backend.

Main areas:

- `app/core/`: runtime config and logging
- `app/integrations/`: mail and LLM adapter boundaries
- `app/routers/`: HTTP route definitions
- `app/schemas/`: request and response models
- `app/services/`: business logic
- `app/storage/`: in-memory store
- `tests/`: backend tests

### `apps/web/`

Next.js host app.

Main areas:

- `app/`: route entry points and global layout
- `public/`: static web assets
- `Dockerfile`: container build for the web host
- `tsconfig.json`: path aliases into `packages/`

### `apps/desktop/`

Future macOS desktop shell.

Main areas:

- `electron/`: main and preload scaffolding
- `tsconfig.json`: path aliases into `packages/`
- `README.md`: desktop shell intent and current status

### `packages/app/`

Shared app shell and route-level composition.

### `packages/features/`

Mail, tasks, calendar, and auth feature workspaces.

### `packages/ui/`

Shared UI chrome and reusable presentation pieces.

### `packages/lib/`

Shared API client, format helpers, and demo data.

### `packages/types/`

Shared TypeScript models for the frontend surfaces.

### `packages/config/`

Shared runtime configuration modules such as API base URL helpers.

### `docs/`

Product and technical design docs for the repo.

### `ui/`

Local ignored checkout of upstream `shadcn/ui` reference material.

Rules:

- intentionally ignored by git
- use as reference only
- do not commit it into this repository
