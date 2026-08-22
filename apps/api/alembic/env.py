"""Alembic environment.

The API owns migrations for the whole platform: the workers share the models but
never change the schema. The URL always comes from the environment.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from matchly_shared.config import get_settings
from matchly_shared.domain import Base
from matchly_shared.domain.columns import GUID

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context) -> str | bool:
    """Render Matchly's portable column types with a real import.

    Without this, autogenerate emits a dotted path it never imports and the
    migration fails with a NameError the first time it runs.
    """
    if type_ == "type" and isinstance(obj, GUID):
        autogen_context.imports.add("from matchly_shared.domain.columns import GUID")
        return "GUID()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
