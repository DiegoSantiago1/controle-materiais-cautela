"""Operações de migração (Alembic) usadas pelos testes e pela carga de dados.

Também serve de linha de comando para atualizar o schema do banco de testes ou do banco da
aplicação (o `alembic upgrade head` atua só no banco principal):
    python -m almox.migracoes teste
    python -m almox.migracoes app
"""

from __future__ import annotations

import argparse
import sys

import psycopg
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from almox.config import RAIZ_PROJETO, ConfigError, carregar_config_banco


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


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aplica as migrações pendentes (upgrade head).")
    parser.add_argument("banco", choices=["teste", "app"])
    args = parser.parse_args(argumentos)
    try:
        config = carregar_config_banco()
        config = (
            config.do_banco_de_teste() if args.banco == "teste" else config.do_banco_da_aplicacao()
        )
        command.upgrade(config_alembic(config.url()), "head")
    except ConfigError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except (psycopg.OperationalError, sqlalchemy.exc.OperationalError) as erro:
        # A recriação do schema passa pelo Alembic (SQLAlchemy), que embrulha o erro do
        # psycopg no dele: sem pegar os dois, o banco fora do ar vira um traceback.
        print(f"Erro: banco inacessível ({erro}).", file=sys.stderr)
        return 1
    print(f"Banco {config.nome!r} no schema mais recente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
