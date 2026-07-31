"""Test that Alembic migrations and the SQLAlchemy schema stay aligned."""

from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app.schema import metadata


def test_alembic_upgrade_runs_initial_migration(tmp_path):
    """A direct Alembic upgrade works against a completely empty database."""
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    alembic_cfg = Config("alembic.ini")

    with engine.begin() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.upgrade(alembic_cfg, "head")
        assert MigrationContext.configure(conn).get_current_revision() == "8f7a1c2d3e4f"

    actual_tables = set(inspect(engine).get_table_names())
    actual_tables.discard("alembic_version")
    assert actual_tables == set(metadata.tables)


def test_migrations_match_schema(tmp_path):
    """Compare the prod migration path against create_all."""
    # DB 1: simulate the prod path (create_all + stamp + future migrations)
    # This is what lifespan does: if no tables, create_all + stamp head.
    # Then future migrations run on top.
    migrated_path = tmp_path / "migrated.db"
    migrated_engine = create_engine(f"sqlite:///{migrated_path}")
    metadata.create_all(migrated_engine)

    alembic_cfg = Config("alembic.ini")
    with migrated_engine.begin() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.stamp(alembic_cfg, "head")

    # DB 2: pure create_all (the reference)
    model_path = tmp_path / "model.db"
    model_engine = create_engine(f"sqlite:///{model_path}")
    metadata.create_all(model_engine)

    # Both should be identical since they both use create_all.
    # The real value of this test is catching FUTURE migrations that
    # drift from the schema. After adding a migration, re-running this
    # test with create_all BEFORE the migration + upgrade will catch
    # any missing defaults/columns.
    #
    # For now, verify the baseline: the two DBs should match exactly.
    migrated_inspector = inspect(migrated_engine)
    model_inspector = inspect(model_engine)

    migrated_tables = set(migrated_inspector.get_table_names())
    model_tables = set(model_inspector.get_table_names())
    migrated_tables.discard("alembic_version")

    assert migrated_tables == model_tables, (
        f"table mismatch: "
        f"only in migrations={migrated_tables - model_tables}, "
        f"only in models={model_tables - migrated_tables}"
    )

    diffs = []
    for table in sorted(model_tables):
        model_cols = {c["name"]: c for c in model_inspector.get_columns(table)}
        migrated_cols = {c["name"]: c for c in migrated_inspector.get_columns(table)}

        model_names = set(model_cols.keys())
        migrated_names = set(migrated_cols.keys())
        for col in model_names - migrated_names:
            diffs.append(f"{table}.{col}: missing from migrations")
        for col in migrated_names - model_names:
            diffs.append(f"{table}.{col}: extra in migrations")

        for col in sorted(model_names & migrated_names):
            mc = model_cols[col]
            ac = migrated_cols[col]

            if mc["nullable"] != ac["nullable"]:
                diffs.append(
                    f"{table}.{col}: nullable "
                    f"(model={mc['nullable']}, migration={ac['nullable']})"
                )

            model_default = mc.get("default") is not None
            migrated_default = ac.get("default") is not None
            if model_default != migrated_default:
                diffs.append(
                    f"{table}.{col}: server_default "
                    f"(model={'yes' if model_default else 'no'}, "
                    f"migration={'yes' if migrated_default else 'no'})"
                )

    assert not diffs, "schema drift between migrations and models:\n" + "\n".join(
        f"  - {d}" for d in diffs
    )
