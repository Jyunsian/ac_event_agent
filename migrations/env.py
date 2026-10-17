import os
from alembic import context
from sqlalchemy import create_engine, pool

url = os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("DATABASE_URL is required for migrations")
if not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("PostgreSQL psycopg URL required; SQLite is unsupported")

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
