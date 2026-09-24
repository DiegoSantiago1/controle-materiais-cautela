"""Funções de apoio usadas pelos testes e pelas fixtures."""

import psycopg
from psycopg.rows import TupleRow

from almox.config import ConfigBanco

type Conexao = psycopg.Connection[TupleRow]


def conectar(config: ConfigBanco, banco: str | None = None) -> Conexao:
    """Conecta como o usuário do projeto (no banco do projeto, ou em outro, se informado)."""
    return psycopg.connect(
        host=config.host,
        port=config.porta,
        dbname=banco or config.nome,
        user=config.usuario,
        password=config.senha,
        connect_timeout=5,
    )
