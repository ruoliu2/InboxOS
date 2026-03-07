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

## Railway

- Git provider repo: `ruoliu2/InboxOS`
- Production Branch: `codex/deploy-vercel-railway`
- Root Directory: `apps/api`
- builder: `apps/api/Dockerfile`
- healthcheck path: `/health`
- public domain: Railway-generated domain
- volume mount: `/data`
- enable `Wait for CI`

Set these production environment variables:

- `APP_ENV=prod`
- `APP_HOST=0.0.0.0`
- `PORT=8000`
- `SESSION_COOKIE_NAME=inboxos_session`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_DB_PATH=/data/auth_sessions.sqlite3`
- `CORS_ORIGINS=https://<vercel-domain>`
- `WEB_BASE_URL=https://<vercel-domain>`
- `GOOGLE_REDIRECT_URI=https://<railway-domain>/auth/google/callback`
- `GOOGLE_CLIENT_ID=<secret>`
- `GOOGLE_CLIENT_SECRET=<secret>`
- `OPENAI_API_BASE=<optional>`
- `OPENAI_API_KEY=<optional>`

## Provisioning Order

1. Create the Railway service, enable public networking, add the `/data` volume, and set the API environment variables except the final Vercel URL values.
2. Push `codex/deploy-vercel-railway` so Railway can build and expose its generated domain.
3. Create the Vercel project and set `NEXT_PUBLIC_API_BASE_URL` to the Railway-generated domain.
4. After Vercel assigns its production URL, update Railway `CORS_ORIGINS`, `WEB_BASE_URL`, and `GOOGLE_REDIRECT_URI`.
5. Update the Google OAuth client with the Vercel web origin and the Railway callback URL.
6. Redeploy both services and verify login, API health, and persistent sessions across a Railway redeploy.

## Acceptance Checks

- `cd apps/web && bun run build`
- `cd apps/api && uv run --group dev python -m pytest`
- `https://<railway-domain>/health` returns `{"ok": true}`
- the deployed web app reaches the Railway API without CORS failures
- Google sign-in completes and redirects back to the Vercel web URL
- the session cookie is secure and HTTP-only
- the session survives a Railway redeploy because SQLite lives on the mounted volume
