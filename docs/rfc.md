# InboxOS MVP RFC

## 1. Summary

InboxOS is a mail-first workspace for Gmail-first users. The frontend is built
in Next.js, and the design direction aims to preserve the same interface across
web and future macOS packaging.

## 2. Goals

- keep one shared UI direction across web and future macOS packaging
- ship a Mail-style three-pane layout first
- support Gmail first and leave room for additional mail providers later
- load inbox summaries quickly and fetch full thread detail on demand
- support direct reply from the mail workspace
- show calendar context and tasks in the same product surface

## 3. Non Goals

- separate native SwiftUI app in v1
- autonomous sending
- full multi-provider rollout in v1
- workflow builder
- PGP or S MIME

## 4. High Level Architecture

```mermaid
graph TD
A1["Next app shared UI"] --> B1["Web runtime"]
A1 --> C1["Future macOS packaging"]
B1 --> D1["FastAPI backend"]
C1 --> D1
D1 --> E1["Mail integration layer"]
E1 --> F1["Current Gmail provider"]
E1 --> G1["Mailbox cache"]
D1 --> H1["Google auth and calendar"]
D1 --> I1["Task service"]
D1 --> J1["Reply send path"]
```

## 5. Tech Choices

### Frontend

- Next.js for shared app
- shadcn/ui for component primitives
- bun for JS package management

Why:

- one codebase for the live web app
- consistent routing and components
- easier path to preserve the same UI in future macOS packaging

### Backend

- Python FastAPI
- uv for Python package management

### Mail Integration

- Google Workspace APIs for the current live implementation
- keep the mail integration layer ready for additional providers later

## 6. Deployment

### MVP deployment plan

- Web: Vercel
- API: Railway

Reason:

- low ops for web and API
- clean separation between frontend and backend services

## 7. Core Flows

### 7.1 Shared UI runtime flow

1. Render the shared Next.js routes in the browser
2. Use a shared API client and shared state model
3. Preserve the same visual direction for future macOS packaging

### 7.2 Email ingestion

1. Connect the mail account through Google OAuth
2. Load the newest thread summaries from the current mail provider
3. Fetch full thread detail only when the user opens a thread or deep link
4. Load older inbox pages as the user scrolls

### 7.3 Mail browsing behavior

- summary-first inbox loading
- on-demand thread detail fetch
- local search over already-loaded summaries
- direct reply from the reading pane

### 7.4 Reply flow

1. User opens a thread in the mail workspace
2. User sends a reply from the compose area
3. Backend updates thread state and returns the updated thread
4. UI refreshes the reading pane and summary list

## 8. UI Contract

### 8.1 Primary layout

Mail-inspired three-pane layout:

- sidebar
- thread list
- reading pane

### 8.2 InboxOS additions

- action chips in thread list rows
- AI summary block in the reading pane
- extracted tasks and deadlines block in the reading pane
- dedicated tasks route
- dedicated calendar route

### 8.3 Why this layout

- familiar mental model
- less custom design work for MVP
- easier parity between web and future macOS packaging

## 9. API Shape

- `GET /auth/google/start`
- `GET /auth/google/callback`
- `GET /auth/session`
- `POST /auth/logout`
- `GET /gmail/threads`
- `GET /gmail/threads/{id}`
- `POST /gmail/threads/{id}/reply`
- `GET /calendar/events`
- `GET /tasks`
- `POST /tasks/create`
- `POST /tasks/{id}/complete`

## 10. Repo Shape

```text
inboxos/
├── apps/
│   ├── web/
│   ├── desktop/
│   └── api/
├── packages/
│   ├── app/
│   ├── ui/
│   ├── features/
│   ├── lib/
│   ├── types/
│   └── config/
├── docs/
├── ui/
└── docker-compose.yml
```

## 11. Key Decisions

### Shared app packages instead of duplicated client UIs

This keeps the live product surface concentrated in shared packages and makes future macOS packaging easier to align.

### In-app tasks before external reminders

Keep action lifecycle inside the product first. External reminder integrations can come later.

### Mail-first surface instead of dashboard-first surface

This keeps the product aligned to the core user workflow.
