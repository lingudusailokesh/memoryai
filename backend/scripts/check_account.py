"""Read-only PostgreSQL account check; never reads password hashes.

Run in the backend's environment: python -m scripts.check_account
Outside Render, use --prompt-database-url to enter the SAME backend database
URL privately. Never pass a database URL or password on the command line.
"""
import argparse
import asyncio
import getpass
import json
import os
import warnings

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


def hidden_input(prompt: str) -> str:
    # getpass otherwise falls back to possibly echoed input without a terminal.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


async def check_account(connection: AsyncConnection, email: str) -> dict[str, bool]:
    try:
        normalized = str(TypeAdapter(EmailStr).validate_python(email)).strip().lower()
        valid = True
    except ValidationError:
        # Also diagnose manually seeded addresses rejected by the login API.
        normalized, valid = email.strip().lower(), False

    async with connection.begin():
        await connection.execute(text("SET TRANSACTION READ ONLY"))
        await connection.execute(text("SET LOCAL statement_timeout = '5s'"))
        if await connection.scalar(text("SHOW transaction_read_only")) != "on":
            raise RuntimeError("Read-only transaction required")
        row = (await connection.execute(text(
            "SELECT "
            "EXISTS(SELECT 1 FROM users WHERE email = :email) AS stored_email_exists, "
            "EXISTS(SELECT 1 FROM users WHERE lower(btrim(email)) = :email "
            "AND email <> :email) AS noncanonical_email_exists"
        ), {"email": normalized})).mappings().one()
        return {
            "read_only": True,
            "login_email_valid": valid,
            "stored_email_exists": bool(row["stored_email_exists"]),
            "noncanonical_email_exists": bool(row["noncanonical_email_exists"]),
        }


async def run(database_url: str, email: str) -> dict[str, bool]:
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername not in {"postgresql+psycopg", "postgresql+asyncpg"}:
        raise ValueError("PostgreSQL URL required")
    # No ORM User load, app import, JWT secret, or hash access is needed.
    engine = create_async_engine(url, echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            return await check_account(connection, email)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-database-url", action="store_true")
    args = parser.parse_args()
    try:
        database_url = (hidden_input("Backend database URL (hidden): ")
                        if args.prompt_database_url else os.environ.get("DATABASE_URL", ""))
        if not database_url:
            print("DATABASE_URL is not injected. Use --prompt-database-url; no query was run.")
            return 2
        email = hidden_input("Account email (hidden): ")
        if not email.strip():
            print("No account email supplied; no query was run.")
            return 2
        print(json.dumps(asyncio.run(run(database_url, email)), sort_keys=True))
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Cancelled; no account was changed.")
        return 2
    except Exception:
        # SQLAlchemy/driver errors may contain credential-bearing URLs or SQL
        # parameters. Do not print a traceback, exception text, or email.
        print("Account check failed. Confirm the backend DB URL, connectivity, and users table privately.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
