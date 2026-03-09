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

## Exact Gamma Release Workflow

Use this flow when a feature branch is ready for the shared gamma environment and all three providers are already configured against the `gamma` branch.

1. Validate the change locally.

```bash
cd apps/api
uv run --group dev python -m pytest
uv run --group dev python -m ruff check

cd ../web
bun run build
```

2. Ensure the feature branch is committed, pushed, and clean.

```bash
git status --short
git push origin HEAD
```

3. Trigger the gamma release from the exact feature-branch commit.

```bash
make deploy-gamma
```

That command runs `./scripts/deploy-branch.sh gamma`, fetches `origin/gamma`, verifies that your current `HEAD` is a fast-forward of `gamma`, and pushes the commit to the `gamma` branch. That single branch update is the shared release trigger for:

- Vercel gamma
- Railway gamma
- Supabase gamma

4. Verify the deployed gamma environment after the provider webhooks finish.

```bash
gh run list --branch gamma --limit 5
curl -fsS https://<gamma-railway-domain>/health
```

Then open the gamma Vercel URL and confirm:

- the web app loads without build or runtime errors
- sign-in redirects back to the gamma web domain
- the gamma web app reaches the gamma Railway API without CORS issues
- mailbox actions and new mail send successfully against gamma

## Exact Production Promotion Workflow

Use the same release path once the exact gamma commit is approved for production.

1. Merge or fast-forward the approved gamma commit into `main`.
2. Run:

```bash
make deploy-main
```

3. Verify production with the matching Railway health endpoint and Vercel URL.

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

### Gamma Vercel Verification

After a `gamma` branch push:

1. Open the gamma Vercel deployment for the pushed commit.
2. Confirm the deployment used `apps/web` as the root directory.
3. Confirm `NEXT_PUBLIC_API_BASE_URL` points at the gamma Railway domain.
4. Open the deployed site and validate the critical flows for that release.

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

### Cross-Origin Session Safety

The current API authenticates browser requests with an HTTP-only session cookie. If you deploy the web app and API on different origins and keep `SESSION_COOKIE_SECURE=true` with cross-origin cookies enabled, you must pair that setup with a CSRF defense before treating it as production-ready for state-changing routes.

For this repo today:

- prefer same-origin deployment for the web app and API when possible
- otherwise require an origin-bound CSRF token or a custom header validated server-side before enabling cross-origin authenticated writes
- do not assume CORS alone protects `POST` form submissions from third-party sites
- when Vercel serves the web app and Railway serves the API on a different origin, the Next server on Vercel does not receive the Railway session cookie; keep auth enforcement and bootstrap on the browser-to-API path rather than Vercel route guards or server prefetch

### Gamma Railway Verification

After a `gamma` branch push:

1. Open the gamma Railway service deployment for the same commit.
2. Confirm the deployment used `apps/api/Dockerfile`.
3. Check the release logs for successful container startup.
4. Confirm the public gamma domain returns a healthy response:

```bash
curl -fsS https://<gamma-railway-domain>/health
```

5. If the deployment boots but the web app fails, double-check:

- `CORS_ORIGINS`
- `WEB_BASE_URL`
- `SESSION_COOKIE_SECURE`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `DATABASE_URL`

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
