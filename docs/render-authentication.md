# Render authentication diagnosis and rollout

## Observed failure

The first deployed frontend `GET /api/health` returned HTTP 502 with Render's
HTML gateway page. The first direct backend health request then took 32.8 seconds
and returned 200. Once awake, frontend registration returned 201 and login 200.
Both direct and proxied `/api/ready` returned 200. This demonstrates transient
startup availability; it does not prove that every previously reported failure
has the same cause. Render service logs were not accessible in the diagnostic
environment. Persistent failures still require the corresponding backend
traceback, Nginx error, and browser request status/body, including `/api/me`.

The original client sent authentication immediately, treated non-JSON gateway
errors as "Check your details and try again", and allowed a failed refresh fetch
to reject session initialization without reaching the anonymous state.

The fix waits up to two minutes for `/api/ready`, with a ten-second limit per
probe and two-second retry delays. Concurrent authentication shares the probe.
Only read-only readiness requests are retried. Login, registration, and refresh
POSTs are sent once; a failure after readiness is reported without replaying the
POST. Startup/network refresh failures resolve to an anonymous session, and
server failures receive an availability message rather than a credentials hint.

## What was ruled out and what remains unknown

- Backend `e2b932d` and frontend `f533cbc` are compatible: all intervening changes
  affect only `frontend/nginx.conf`. `e2b932d` adds `psycopg[binary]`; `b5ffb46`
  already contains the same authentication routes, frontend API client, models,
  and migrations. The historical build/startup failures of `b5ffb46` cannot be
  diagnosed from its commit message without deployment logs.
- The frontend sends relative `/api/auth/register`, `/api/auth/login`, and
  `/api/me` requests with credentials included. Nginx preserves `/api/`, uses
  the intended `memoryai-jp1f.onrender.com` HTTPS upstream, and supplies matching
  SNI and Host. Authentication works through that deployed proxy. Browser calls
  are same-origin, so cross-origin preflight is not the authentication path.
- Nginx forwards `$scheme` as `X-Forwarded-Proto`; behind Render TLS termination
  that can be HTTP. The authentication routes use the configured cookie flag,
  not that header. Verified production refresh cookies have `Secure`,
  `HttpOnly`, `SameSite=Lax`, and `Path=/api/auth`, on the frontend domain.
- Authentication uses real Argon2id password hashing, HS256 access tokens kept
  in browser memory, and hashed, rotating refresh tokens in the database. Live
  registration, fresh-session login, refresh, and protected-page access passed.
  The deployed database supports these queries and persists the test account.
  Its credentials, exact URL/driver, Alembic stamp, and service configuration were
  not exposed or inspected; readiness alone does not prove the migration stamp.
- Most pytest authentication tests substitute SQLite and mocked AI providers.
  The four Postgres tests exercise memory, not Render authentication or Nginx.
  The former onboarding functional check used Vite's development proxy.
- Onboarding changed no tracked repository files. `/tmp/memoryai-install.sh`
  and saved environment instructions install a virtualenv and npm dependencies,
  preserve/create ignored local `.env` files with a development JWT secret,
  start the local Compose database, create a separate test database, and apply
  local migrations. Generated dependencies, build outputs, caches, and local
  Postgres state are retained locally. This script was not a Render deployment
  script and never configured either Render service.

## Validation

- `cd frontend && npm test`: six regression tests passed. Five fail against the
  original client. Coverage includes gateway/network/HTML startup responses,
  readiness timeout, shared readiness, rejected credentials, and no POST replay.
- `cd frontend && npm run typecheck && npm run build`: passed; the existing large
  bundle warning remains nonblocking.
- Backend pytest against a dedicated local pgvector test database: 159 passed.
  Local authentication also passed using the psycopg async driver and real
  migrated Postgres, without database dependency overrides.
- The shipped Nginx configuration was run in Nginx 1.27.5 against a local HTTPS
  fixture requiring correct SNI and Host, forwarding to FastAPI and real
  Postgres. Registration, login, refresh, persistence, and protected Settings
  and dashboard pages passed in Chromium. With the new built client, two
  injected readiness 502 responses were recovered before authentication.
- The currently deployed, original frontend passed warmed Chromium registration,
  login after clearing cookies, protected Settings/dashboard access, and page
  reload session restoration. Disposable production accounts were left intact;
  no existing users or production records were modified or deleted. This is
  baseline verification, not proof that the patch has been deployed.

## Required rollout

Only redeploy **memoryai-frontend** (`srv-db1usn3bc2fs73eishag`) with this frontend
change from `main`. Preserve its existing Docker root-directory and Dockerfile
settings. The repository Dockerfile is `frontend/Dockerfile`; if the service root
is `frontend`, its relative path is `Dockerfile`. No build/start-command override,
new environment variable, secret, database reset, or manual migration is needed
for this fix. The existing backend already provides `/api/ready`.

**memoryai** (`srv-db1u3ih7lnhs73cs0dc0`) needs no code/configuration change for
this rollout. Preserve its working database URL, JWT secret, provider credentials,
and secure-cookie setting. If a separate backend rollout is needed later, its
Dockerfile already runs `alembic upgrade head` before Uvicorn; never stamp over
missing schema or point destructive tests at the production database.

After frontend deployment, verify `/api/ready` through the frontend, create a
new disposable account, clear the browser session and log in with that account,
open Settings, and reload to verify refresh. Confirm the new hashed JS asset
matches the build. For a cold-start check, wait for the free services to become
idle naturally and verify that readiness probes precede a single authentication
POST. Do not restart the production database to simulate cold startup.
