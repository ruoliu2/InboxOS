# Vercel And Railway Runbook

This runbook defines the production deployment flow for the current MVP.

## Release Branch

- deploy branch: `codex/deploy-vercel-railway`
- deploy worktree: `../InboxOS-deploy`
- create once:

```bash
git fetch origin main
git worktree add -b codex/deploy-vercel-railway ../InboxOS-deploy origin/main
cd ../InboxOS-deploy
git push -u origin codex/deploy-vercel-railway
```

- update for each release:

```bash
cd ../InboxOS-deploy
git fetch origin main
git merge --no-ff origin/main
git push
```

Use `git commit -s -S` for any direct commits or merge-resolution commits made on the deploy branch.

## Vercel

- Git provider repo: `ruoliu2/InboxOS`
- Production Branch: `codex/deploy-vercel-railway`
- Root Directory: `apps/web`
- Build Command: `bun run build`
- Start Command: `bun run start`
- enable source files outside the root directory

Set these production environment variables:

- `NEXT_PUBLIC_API_BASE_URL=https://<railway-domain>`
- `NEXT_PUBLIC_SESSION_COOKIE_NAME=inboxos_session`

Do not set Supabase database credentials or service keys in Vercel for the current architecture.

## Railway

- Git provider repo: `ruoliu2/InboxOS`
- Production Branch: `codex/deploy-vercel-railway`
- Root Directory: `apps/api`
- builder: `apps/api/Dockerfile`
- healthcheck path: `/health`
- public domain: Railway-generated domain
- volume mount: optional `/data` only if you want persisted Gmail cache
- enable `Wait for CI`

Set these production environment variables:

- `APP_ENV=prod`
- `APP_HOST=0.0.0.0`
- `PORT=8000`
- `DATABASE_URL=<supabase session pooler url>`
- `CREDENTIAL_ENCRYPTION_KEY=<secret>`
- `SESSION_COOKIE_NAME=inboxos_session`
- `SESSION_COOKIE_SECURE=true`
- `CORS_ORIGINS=https://<vercel-domain>`
- `WEB_BASE_URL=https://<vercel-domain>`
- `GOOGLE_REDIRECT_URI=<optional explicit override>`
- `GOOGLE_CLIENT_ID=<secret>`
- `GOOGLE_CLIENT_SECRET=<secret>`
- `GMAIL_CACHE_DB_PATH=/data/gmail_mailbox_cache.sqlite3` if you keep the volume for cache persistence

If `GOOGLE_REDIRECT_URI` is unset, Railway deployments fall back to `RAILWAY_PUBLIC_DOMAIN` for the callback URL.

Use the Supabase project connection string from the project connect screen. Prefer the pooled connection string on Railway for the API service.

## Supabase

- local dev: run `supabase start` from the repo root
- local reset: run `supabase db reset`
- production setup:
  - create one production Supabase project
  - copy the project Postgres password and pooled connection string into Railway
  - run `supabase login`
  - run `supabase link --project-ref <project-ref>`
  - run `supabase db push`

Do not enable Supabase Auth or direct browser-to-database access for this phase. The API remains the only service that talks to Postgres.

## Provisioning Order

1. Create the Supabase production project and capture the pooled Postgres connection string plus database password.
2. Create the Railway service, enable public networking, optionally add the `/data` volume for Gmail cache, and set the API environment variables except the final Vercel URL values.
3. Push `codex/deploy-vercel-railway` so Railway can build and expose its generated domain.
4. Create the Vercel project and set `NEXT_PUBLIC_API_BASE_URL` to the Railway-generated domain.
5. After Vercel assigns its production URL, update Railway `CORS_ORIGINS` and `WEB_BASE_URL`.
6. Update the Google OAuth client with the Vercel web origin and the Railway callback URL.
7. Run `supabase link --project-ref <project-ref>` and `supabase db push` from the deploy worktree.
8. Redeploy both services and verify login, API health, and persistent sessions across a Railway redeploy.

## Acceptance Checks

- `cd apps/web && bun run build`
- `cd apps/api && uv run --group dev python -m pytest`
- `https://<railway-domain>/health` returns `{"ok": true}`
- the deployed web app reaches the Railway API without CORS failures
- Google sign-in completes and redirects back to the Vercel web URL
- the session cookie is secure and HTTP-only
- the session survives a Railway redeploy because auth state lives in Supabase
