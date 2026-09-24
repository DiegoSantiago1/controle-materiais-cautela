"""Ambiente do Alembic, adaptado do template oficial (`alembic init`).

Diferenças em relação ao template:
- A URL do banco vem do .env (almox.config), e não do alembic.ini, que é versionado.
- Sem autogenerate: target_metadata = None. As migrações são SQL escrito à mão
  (op.execute), de propósito, como no Projeto 1.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from almox.config import carregar_config_banco

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade --sql`): só gera o SQL, sem conectar ao banco."""
    context.configure(
        url=carregar_config_banco().url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo normal: conecta e aplica as migrações.

    No PostgreSQL o DDL é transacional: se uma migração falhar no meio, nada dela fica
    aplicado.
    """
    connectable = create_engine(carregar_config_banco().url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
