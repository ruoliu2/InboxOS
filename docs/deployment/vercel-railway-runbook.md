# Vercel, Railway, And Supabase Runbook

This runbook defines the branch-to-environment deployment flow for the current MVP.

## Branch Contract

- `main` auto deploys production
- `staging` auto deploys staging
- use GitHub pull requests to promote changes from feature branches into `staging`, then from `staging` into `main`
- create the `staging` branch once:

```bash
git fetch origin main
git branch staging origin/main
git push -u origin staging
```

Use `git commit -s -S` for any direct commits or merge-resolution commits made on `staging` or `main`.

## Vercel

- Git provider repo: `ruoliu2/InboxOS`
- production project branch: `main`
- staging project branch: `staging`
- Root Directory: `apps/web`
- Build Command: `bun run build`
- Start Command: `bun run start`
- enable source files outside the root directory

Set these environment variables in both projects:

- `NEXT_PUBLIC_API_BASE_URL=https://<railway-domain-for-that-environment>`
- `NEXT_PUBLIC_SESSION_COOKIE_NAME=inboxos_session`

## Railway

- Git provider repo: `ruoliu2/InboxOS`
- production environment branch: `main`
- staging environment branch: `staging`
- Root Directory: `apps/api`
- builder: `apps/api/Dockerfile`
- healthcheck path: `/health`
- public domain: Railway-generated domain per environment
- volume mount: `/data` with a separate volume per environment
- enable `Wait for CI`

Set these environment variables for production:

- `APP_ENV=prod`
- `APP_HOST=0.0.0.0`
- `PORT=8000`
- `SESSION_COOKIE_NAME=inboxos_session`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_DB_PATH=/data/auth_sessions.sqlite3`
- `CORS_ORIGINS=https://<vercel-domain>`
- `WEB_BASE_URL=https://<vercel-domain>`
- `GOOGLE_REDIRECT_URI=<optional explicit override>`
- `GOOGLE_CLIENT_ID=<secret>`
- `GOOGLE_CLIENT_SECRET=<secret>`

Set these environment variables for staging:

- `APP_ENV=staging`
- `APP_HOST=0.0.0.0`
- `PORT=8000`
- `SESSION_COOKIE_NAME=inboxos_session`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_DB_PATH=/data/auth_sessions.sqlite3`
- `CORS_ORIGINS=https://<staging-vercel-domain>`
- `WEB_BASE_URL=https://<staging-vercel-domain>`
- `GOOGLE_REDIRECT_URI=<optional explicit override>`
- `GOOGLE_CLIENT_ID=<secret>`
- `GOOGLE_CLIENT_SECRET=<secret>`

If `GOOGLE_REDIRECT_URI` is unset, Railway deployments fall back to `RAILWAY_PUBLIC_DOMAIN` for the callback URL.

## Supabase

- workflow: `.github/workflows/supabase-release.yml`
- production GitHub environment: `production`
- staging GitHub environment: `staging`
- initialize the repo with `supabase init` before the first remote release
- commit remote schema changes under `supabase/migrations`
- commit remote edge functions under `supabase/functions`

Set these GitHub environment secrets in both `production` and `staging`:

- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_PROJECT_ID`
- `SUPABASE_DB_PASSWORD`

On each push to `main` or `staging`, the workflow:

- links the branch to the matching remote Supabase project
- pushes pending migrations when `supabase/migrations` exists
- deploys all edge functions when `supabase/functions` exists
- exits cleanly when the repo has not been initialized with a `supabase/` directory yet

## Provisioning Order

1. Push the new `staging` branch so all providers can bind their staging environment to a stable branch.
2. Create the Railway staging environment or service, enable public networking, add the `/data` volume, and set its staging API variables except the final staging Vercel URL values.
3. Create the Vercel staging project, set its Production Branch to `staging`, and point `NEXT_PUBLIC_API_BASE_URL` at the staging Railway domain.
4. Create the Supabase staging project and add its secrets to the GitHub `staging` environment.
5. After staging is healthy, create the production Railway environment or service on `main`, plus the production Vercel project and production Supabase project.
6. Update Railway `CORS_ORIGINS` and `WEB_BASE_URL` in each environment to the matching Vercel domain.
7. Update the Google OAuth client with both Vercel origins and both Railway callback URLs if the same OAuth app is shared across staging and production.
8. Verify staging from `staging`, then promote the same commit to `main`.

## Acceptance Checks

- `cd apps/web && bun run build`
- `cd apps/api && uv run --group dev python -m pytest`
- `https://<staging-railway-domain>/health` returns `{"ok": true}`
- `https://<production-railway-domain>/health` returns `{"ok": true}`
- both deployed web apps reach their matching Railway API without CORS failures
- Google sign-in completes and redirects back to the matching Vercel web URL in each environment
- the session cookie is secure and HTTP-only
- the session survives a Railway redeploy in both environments because SQLite lives on the mounted volume
- Supabase migrations and edge functions land in the matching staging or production project after branch pushes
