# Forgot password

Flow: **Log in page -> "Forgot password?" -> enter email -> link by email (valid 30 min) -> choose new password -> log in.**

## Backend
- `POST /api/auth/forgot-password {email}` always answers `202` with the same message, whether or not the email has an account.
  If it does, a one-time token is created and the email is sent *after* the response (so response time doesn't reveal it either).
  At most one email per account per minute; a new link voids older unused ones.
- `POST /api/auth/reset-password {token, password}` -> `204`, or `400` for an unknown, used or expired token.
  The token is consumed atomically (one `UPDATE ... RETURNING`), so it cannot be used twice, even concurrently.
  A successful reset also revokes every refresh token, signing the user out everywhere.
- Tokens: 48 random bytes, only the SHA-256 hash is stored (`password_reset_tokens`).

## Frontend
`/forgot-password` and `/reset-password?token=...`. The reset page removes the token from the address bar right away and sends `no-referrer`.

## Email delivery (`EMAIL_BACKEND`)
- `console` (default): the email, including the link, is printed in the backend terminal. Development only.
- `smtp`: any provider with STARTTLS on port 587. Gmail needs 2-step verification plus an "app password"; Brevo and Mailtrap give SMTP credentials in their dashboards. Check each provider's current free allowance yourself.

## Not covered yet
Proper per-IP rate limiting and lockout (Stage 10), email verification at signup, "change password" while logged in (Stage 10 settings).
The "email exists or not" check differs in timing by one database insert at most; accepted for now.
