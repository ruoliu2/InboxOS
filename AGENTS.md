# AGENTS

## Scope

These instructions apply to the InboxOS repo.

## Frontend Standard

- Prefer Tailwind utility classes for new UI work.
- Use Radix primitives for interactive behavior such as dialogs, dropdown menus, and layered overlays.
- Put shared UI primitives and wrappers in `packages/ui/src`.
- Keep `apps/web/app/globals.css` limited to design tokens, shell/layout rules, and legacy layout that has not been migrated yet.
- Do not add new feature-specific CSS blocks to `globals.css` when the same result is practical with Tailwind.
- Prefer small reusable wrappers around Radix and native elements over one-off duplicated markup.

## Component Structure

- Split large feature files when they contain separate surfaces such as dialogs, toolbars, tables, or side panels.
- Prefer sibling files inside the same feature folder for extracted pieces, for example `mail/new-message-composer.tsx`.
- Keep route hosts thin; shared behavior belongs in `packages/features` and shared primitives belong in `packages/ui`.

## Validation

- For web UI changes, run `bun run build` in `apps/web`.
- Run `uvx pre-commit run --files ...` on changed frontend files before finishing.

## Repo Notes

- `apps/web` is the active web host.
- `packages/features` contains mail, calendar, tasks, and auth surfaces.
- `packages/ui` contains shared UI primitives and app chrome.
- `ui/` is a local ignored upstream `shadcn/ui` reference checkout, not the source of truth for product code.
