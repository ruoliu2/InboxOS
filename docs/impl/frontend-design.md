# Frontend Design

Frontend host: `apps/web/`

Shared frontend source of truth: `packages/`

## Framework And Entry Points

- Next.js app router in `apps/web/app`
- root layout in `apps/web/app/layout.tsx`
- global styles in `apps/web/app/globals.css`
- shared shell in `packages/app/src/app-shell.tsx`
- compact app rail in `packages/ui/src/app-rail.tsx`
- shared Tailwind config in `apps/web/tailwind.config.ts`
- shared UI primitives in `packages/ui/src`

## UI Standard

- default to Tailwind utility classes for component styling
- use Radix primitives for interactive UI such as dialogs and menus
- keep shared UI building blocks in `packages/ui/src`
- keep `globals.css` for tokens, app-shell layout, and legacy layout rules only
- avoid adding new feature-specific class blocks to `globals.css` when Tailwind can express the same layout
- prefer native inputs styled with Tailwind unless a richer Radix primitive is necessary
- when a feature file grows beyond a few hundred lines or mixes multiple surfaces, split child views or dialogs into sibling files

## Route Ownership

### Web host routes

- `apps/web/app/page.tsx`: entry route that redirects to `/mail`
- `apps/web/app/mail/page.tsx`: mail host route
- `apps/web/app/tasks/page.tsx`: tasks host route
- `apps/web/app/calendar/page.tsx`: calendar host route
- `apps/web/app/auth/page.tsx`: auth host route
- `apps/web/app/api/health/route.ts`: simple web-side health route

### Shared route composition

- `packages/app/src/routes/mail-page.tsx`
- `packages/app/src/routes/tasks-page.tsx`
- `packages/app/src/routes/calendar-page.tsx`
- `packages/app/src/routes/auth-page.tsx`

These files let multiple host apps mount the same feature screens without duplicating route assembly logic.

## Mail Surface

Primary files:

- `packages/features/src/mail/mail-workspace.tsx`
- `packages/features/src/mail/new-message-composer.tsx`

Responsibilities:

- load the first page of thread summaries from the backend
- load selected thread detail in the reading pane on demand
- filter list between `all` and `unread`
- keep search limited to the thread summaries already loaded in the client
- load older inbox pages with infinite scroll
- send replies through `POST /gmail/threads/{thread_id}/reply`
- update the selected thread and summary list in place after reply

Implementation notes:

- unread is derived from action states rather than a mailbox unread flag
- the current live mail flow does not use mock thread data
- real API mode uses the backend response as the source of truth after reply

## Tasks Surface

Primary file: `packages/features/src/tasks/tasks-view.tsx`

Responsibilities:

- list tasks from the backend
- support search and filtering
- create tasks through the API when available
- complete tasks through the API when available
- fall back to local mock task data in demo mode

## Calendar Surface

Primary files:

- `packages/features/src/calendar/calendar-workspace.tsx`
- `packages/features/src/calendar/calendar-dialogs.tsx`

Responsibilities:

- render month, week, and day calendar views
- keep a macOS-style segmented control for switching views
- load Google Calendar events through the backend
- show backend load errors inline if the fetch fails

## Auth Surface

Primary file: `packages/features/src/auth/auth-view.tsx`

Responsibilities:

- trigger Google auth start flow through the backend
- restore the current session through the backend
- present the login and connection entry UI

## Shared Client Modules

- `packages/lib/src/api.ts`: API client used by the feature workspaces
- `packages/lib/src/format.ts`: display helpers
- `packages/lib/src/mock-data.ts`: demo fallback task data
- `packages/types/src/index.ts`: shared frontend data types
- `packages/config/src/web.ts`: API base URL config
