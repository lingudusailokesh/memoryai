import os
import uuid
import asyncio
import json

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.check_account import check_account, main


def test_account_check_requires_explicit_database_configuration(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["check_account"])
    assert main() == 2
    assert "no query was run" in capsys.readouterr().out


def test_account_check_does_not_print_connection_errors(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "not-a-valid-secret-database-url")
    monkeypatch.setattr("sys.argv", ["check_account"])
    monkeypatch.setattr("scripts.check_account.getpass.getpass", lambda _: "private@example.com")
    assert main() == 1
    output = capsys.readouterr().out
    assert "private@example.com" not in output and "secret-database-url" not in output


def test_account_check_refuses_echoed_secret_input(monkeypatch, capsys):
    import getpass
    import warnings

    monkeypatch.setattr("sys.argv", ["check_account", "--prompt-database-url"])

    def unsafe_prompt(_):
        warnings.warn("Input would be echoed", getpass.GetPassWarning)
        raise AssertionError("Must refuse before reading a credential")

    monkeypatch.setattr("scripts.check_account.getpass.getpass", unsafe_prompt)
    assert main() == 1
    assert "Input would be echoed" not in capsys.readouterr().out


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="dedicated test Postgres required")
async def test_account_check_reads_only_email_booleans_in_read_only_transaction(monkeypatch, capsys):
    # This creates/removes only a disposable schema in TEST_POSTGRES_URL, never
    # the configured application DB. No password/hash column exists to load.
    engine = create_async_engine(os.environ["TEST_POSTGRES_URL"], hide_parameters=True)
    schema = "account_check_" + uuid.uuid4().hex
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'CREATE TABLE "{schema}".users (email TEXT NOT NULL)'))
                await connection.execute(text(f'INSERT INTO "{schema}".users VALUES (:email)'), {"email": "ada@example.com"})
                await connection.execute(text(f'INSERT INTO "{schema}".users VALUES (:email)'), {"email": " Legacy@EXAMPLE.com "})
                await connection.execute(text(f'SET search_path TO "{schema}"'))
            found = await check_account(connection, " ADA@EXAMPLE.COM ")
            assert found == {"read_only": True, "login_email_valid": True,
                             "stored_email_exists": True, "noncanonical_email_exists": False}
            absent = await check_account(connection, "absent@example.com")
            assert absent["stored_email_exists"] is False
            legacy = await check_account(connection, "legacy@example.com")
            assert legacy["stored_email_exists"] is False and legacy["noncanonical_email_exists"] is True
            invalid = await check_account(connection, "demo@memoryai.local")
            assert invalid["login_email_valid"] is False
            # Exercise the complete CLI with an independently connected psycopg
            # session, preserving private inputs and boolean-only stdout.
            url = make_url(os.environ["TEST_POSTGRES_URL"]).set(drivername="postgresql+psycopg")
            url = url.update_query_dict({"options": f"-csearch_path={schema}"})
            monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
            monkeypatch.setattr("sys.argv", ["check_account"])
            monkeypatch.setattr("scripts.check_account.getpass.getpass", lambda _: "ADA@example.com")
            assert await asyncio.to_thread(main) == 0
            assert json.loads(capsys.readouterr().out) == found
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
