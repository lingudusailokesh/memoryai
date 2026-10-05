import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


def _repair_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0008_repair_product_finish_schema.py"
    spec = importlib.util.spec_from_file_location("repair_0008", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_migration_restores_schema_for_a_database_stamped_at_0007() -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("email", sa.String(320)))
    sa.Table("messages", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    metadata.create_all(engine)

    migration = _repair_module()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        old_proxy = getattr(op, "_proxy", None)
        op._proxy = Operations(context)
        try:
            migration.upgrade()
            migration.upgrade()  # idempotent: safe if a deploy retries the migration
        finally:
            if old_proxy is None:
                del op._proxy
            else:
                op._proxy = old_proxy

        inspector = sa.inspect(connection)
        assert {"name", "memory_globally_enabled", "memory_top_k", "memory_threshold", "custom_instructions"} <= {column["name"] for column in inspector.get_columns("users")}
        assert {"usage_events", "memory_retrievals"} <= set(inspector.get_table_names())
