# Vercel, Railway, And Supabase Runbook

This runbook defines the branch-to-environment deployment flow for the current MVP.

## Branch Contract

- `main` auto deploys production
- `gamma` auto deploys gamma
- use GitHub pull requests to promote changes from feature branches into `gamma`, then from `gamma` into `main`
- create the `gamma` branch once:

```bash
git fetch origin main
git branch gamma origin/main
git push -u origin gamma
```

Use `git commit -s -S` for any direct commits or merge-resolution commits made on `gamma` or `main`.

## Vercel

- Git provider repo: `ruoliu2/InboxOS`
- production project branch: `main`
- gamma project branch: `gamma`
- Root Directory: `apps/web`
- Build Command: `bun run build`
- Start Command: `bun run start`
- enable source files outside the root directory

Set these environment variables in both projects:

- `NEXT_PUBLIC_API_BASE_URL=https://<railway-domain-for-that-environment>`
- `NEXT_PUBLIC_SESSION_COOKIE_NAME=inboxos_session`

Do not set Supabase database credentials or service keys in Vercel for the current architecture.

## Railway

- Git provider repo: `ruoliu2/InboxOS`
- production environment branch: `main`
- gamma environment branch: `gamma`
- Root Directory: `apps/api`
- builder: `apps/api/Dockerfile`
- healthcheck path: `/health`
- public domain: Railway-generated domain per environment
- volume mount: optional `/data` only if you want persisted Gmail cache
- enable `Wait for CI`

Set these environment variables for production:

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

Set these environment variables for gamma:

- `APP_ENV=gamma`
- `APP_HOST=0.0.0.0`
- `PORT=8000`
- `DATABASE_URL=<gamma supabase session pooler url>`
- `CREDENTIAL_ENCRYPTION_KEY=<secret>`
- `SESSION_COOKIE_NAME=inboxos_session`
- `SESSION_COOKIE_SECURE=true`
- `CORS_ORIGINS=https://<gamma-vercel-domain>`
- `WEB_BASE_URL=https://<gamma-vercel-domain>`
- `GOOGLE_REDIRECT_URI=<optional explicit override>`
- `GOOGLE_CLIENT_ID=<secret>`
- `GOOGLE_CLIENT_SECRET=<secret>`
- `GMAIL_CACHE_DB_PATH=/data/gmail_mailbox_cache.sqlite3` if you keep the volume for cache persistence

If `GOOGLE_REDIRECT_URI` is unset, Railway deployments fall back to `RAILWAY_PUBLIC_DOMAIN` for the callback URL.

## Supabase

- workflow: `.github/workflows/supabase-release.yml`
- production GitHub environment: `production`
- gamma GitHub environment: `gamma`
- initialize the repo with `supabase init` before the first remote release
- commit remote schema changes under `supabase/migrations`
- commit remote edge functions under `supabase/functions`

Set these GitHub environment secrets in both `production` and `gamma`:

- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_PROJECT_ID`
- `SUPABASE_DB_PASSWORD`

On each push to `main` or `gamma`, the workflow:

- links the branch to the matching remote Supabase project
- pushes pending migrations when `supabase/migrations` exists
- deploys all edge functions when `supabase/functions` exists
- exits cleanly when the repo has not been initialized with a `supabase/` directory yet

## Provisioning Order

1. Push the new `gamma` branch so all providers can bind their gamma environment to a stable branch.
2. Create the Supabase gamma project and add its secrets to the GitHub `gamma` environment.
3. Create the Railway gamma environment or service, enable public networking, optionally add the `/data` volume for Gmail cache, and set its gamma API variables except the final gamma Vercel URL values.
4. Create the Vercel gamma project, set its Production Branch to `gamma`, and point `NEXT_PUBLIC_API_BASE_URL` at the gamma Railway domain.
5. After gamma is healthy, create the production Supabase project, production Railway environment or service on `main`, and the production Vercel project.
6. Update Railway `CORS_ORIGINS` and `WEB_BASE_URL` in each environment to the matching Vercel domain.
7. Update the Google OAuth client with both Vercel origins and both Railway callback URLs if the same OAuth app is shared across gamma and production.
8. Verify gamma from `gamma`, then promote the same commit to `main`.

## Acceptance Checks

- `cd apps/web && bun run build`
- `cd apps/api && uv run --group dev python -m pytest`
- `https://<gamma-railway-domain>/health` and `https://<production-railway-domain>/health` both return `{"ok": true}`
- both deployed web apps reach their matching Railway API without CORS failures
- Google sign-in completes and redirects back to the matching Vercel web URL in each environment
- the session cookie is secure and HTTP-only
- the session survives a Railway redeploy because auth state lives in Supabase
- Supabase migrations and edge functions land in the matching gamma or production project after branch pushes
