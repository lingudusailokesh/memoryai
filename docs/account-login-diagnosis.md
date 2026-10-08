# Diagnose a deployed account returning 401

## What the response establishes

`POST /api/auth/login` returning `401` with `Incorrect email or password` comes
from `AuthService.login`: either the normalized email was not found in the
backend's current database, or Argon2 verification failed. Both deliberately
return the same message. Token issuance and refresh-cookie creation happen only
after this check. A database connection/schema exception is not converted into
this credentials response. A `401` from `/api/auth/refresh` without a valid
refresh cookie is expected and does not explain a password-login failure.

The Windows Chrome screenshot shows the deployed `index-DbClOssp.js` client
receiving that credentials response. The user's reported time is approximately
11:04 AM IST on October 7, 2026 (05:34 UTC). The screenshot does not show the
submitted email or password, or a successful registration for that account.
HeadlessChrome successes belong to disposable automated accounts and do not
prove the user's account exists or that their password matches.

Registration and login both use `EmailStr`; the repository then strips outer
email whitespace and lowercases the stored/looked-up email. Passwords are
hashed with Argon2id and verified exactly, including case, spaces, and Unicode.
Passwords must not be trimmed or changed to make verification pass. The client
submits the entered password unchanged. There is no Windows/headless-specific
authentication branch, demo fallback, or universally valid demo account.

Registration writes only to the `DATABASE_URL` configured for that backend.
Local Compose data, local `.env` files, and seeded accounts are not copied to
Render by deploying a Git commit or running migrations. A local account exists
in production only if both environments deliberately use the same database.
For this user's account, registration was attempted on Render, but its original
201 response and subsequent database-configuration history could not be
confirmed. Do not infer account existence from another user's registration.

## Read-only account-existence check

Use `backend/scripts/check_account.py` from this checkout. It executes a
parameterized `SELECT EXISTS` under `SET TRANSACTION READ ONLY`, verifies that
read-only mode is active, and has a five-second statement timeout. It selects
only email-existence booleans, never an ORM user, password, password hash, token,
or database URL. Inputs are hidden, and errors are sanitized. It refuses a
missing database binding rather than silently querying the local default DB.

In an interactive backend shell with the **current** `memoryai` service's
`DATABASE_URL` injected, run from the backend directory (`/app` in its Docker
image) using the existing Python environment:

```sh
python -m scripts.check_account
```

If that script is not present on the deployed service, or the free service does
not provide a shell, run the helper locally from the repository's `backend`
directory with its virtualenv/dependencies active:

```sh
python -m scripts.check_account --prompt-database-url
```

Privately enter the external PostgreSQL connection URL for the **same database
currently bound to the backend**, then the exact email you entered at login.
Choose the external URL of that database for a local connection; an internal
Render hostname may not resolve outside Render. Preserve SSL options. Do not
paste the URL into chat, a command argument, a script, or a shared screenshot.
Use an interactive terminal; the helper refuses unsafe echoed-input fallback.
No production redeploy is needed to run this local read-only check.

The output contains only:

```json
{
  "read_only": true,
  "login_email_valid": true,
  "stored_email_exists": false,
  "noncanonical_email_exists": false
}
```

- Valid email, neither match exists: that email has no account in the checked
  database. Register on the deployed `/register` page. Confirm the registration
  request itself returned 201 and `/api/me` returned 200. If older data was
  expected, first have the owner verify which database is bound to the backend.
- Stored email exists: account absence is ruled out for that database. Re-enter
  the original password without autofill, check keyboard layout/Caps Lock, and
  preserve any intentional spaces. The check does not verify passwords or hash
  integrity. Use self-service recovery if the original password is unknown.
- Only a noncanonical email matches: a legacy/manual record exists with a
  different stored case or outer spaces. Neither this helper nor the seed fix
  renames that record. Investigate its creation before modifying authentication
  or creating a second account.
- Invalid login email: the API rejects that address with 422. The former local
  seed used `demo@memoryai.local`, which is rejected. This is a separate demo
  utility defect, not the shown 401. New local seeds use `demo@example.com`;
  existing records are untouched. Never seed the production database to create
  a publicly known demo password.

## Recovery and verification

For an existing account whose original password cannot be supplied, the user
can choose **Forgot password?** on the deployed login page and follow the link
sent to their mailbox. The response is always 202, including for absent accounts,
so it is not an account-existence check. No password reset is performed by this
diagnosis or helper. Keep reset links and tokens private.

Email delivery must be configured: `EMAIL_BACKEND=smtp` with the owner's existing
SMTP provider settings and credentials stored securely in Render, and
`FRONTEND_URL=https://memoryai-frontend.onrender.com`. If configured as `console`,
the backend logs the link instead of emailing it; that development default must
not be mistaken for working production email delivery. The current Render email
configuration and actual delivery were not accessible for verification.

After confirming/registering the intended account, test in the user's Windows
Chrome browser:

1. Register at the deployed site if absent; require `/api/auth/register` 201 and
   `/api/me` 200. A 409 means that email is already registered; use login/recovery.
2. Open Settings to verify protected-page access.
3. Click **Log out**; require `/api/auth/logout` 204. A later refresh returning
   401 while logged out is expected.
4. Log in with the same email and exact password; require `/api/auth/login` 200,
   followed by `/api/me` 200, then reload to verify session restoration.

No authentication, frontend, database URL, JWT, schema, or migration change is
required solely because of this 401. The confirmed fix changes only future
local demo seeding. The helper and tests can be reviewed without redeploying
either Render application. If production recovery email is confirmed missing,
configure SMTP securely and redeploy only the backend `memoryai`; preserve its
existing database and JWT secret.
