"""Operações de migração (Alembic) usadas pelos testes e pela carga de dados."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from almox.config import RAIZ_PROJETO


def config_alembic(url: URL) -> Config:
    """Config do Alembic apontando para a URL informada (em vez da URL do .env)."""
    config = Config(str(RAIZ_PROJETO / "alembic.ini"))
    config.attributes["url"] = url
    return config


def recriar_schema(url: URL) -> None:
    """Desfaz todas as migrações e aplica de novo: banco vazio, no schema mais recente.

    É o único jeito de zerar o banco: o histórico de movimentações é imutável (não
    aceita DELETE nem TRUNCATE), mas as migrações podem remover a tabela inteira.
    """
    config = config_alembic(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
