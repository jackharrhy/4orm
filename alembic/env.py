from alembic import context
from app.db import DATABASE_URL
from app.schema import metadata

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)
target_metadata = metadata


def run_migrations_offline():
    context.configure(
        url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # Support passing a connection via config attributes (for tests)
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        from sqlalchemy import create_engine

        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
