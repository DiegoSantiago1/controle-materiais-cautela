"""Acesso ao banco: conexão e chamada das funções de movimentação do schema core."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from almox.config import ConfigBanco

type Conexao = psycopg.Connection[TupleRow]


def conectar(config: ConfigBanco, banco: str | None = None) -> Conexao:
    """Conecta como o usuário do projeto (no banco da config, ou em outro, se informado)."""
    return psycopg.connect(
        host=config.host,
        port=config.porta,
        dbname=banco or config.nome,
        user=config.usuario,
        password=config.senha,
        connect_timeout=5,
    )


def comando_funcao(nome: str, parametros: list[str]) -> sql.Composed:
    """Monta `SELECT core.<nome>(p1 => %(p1)s, ...)`.

    Nomes viram identificadores citados e valores viram placeholders: nada do que é
    passado é concatenado como texto SQL.
    """
    argumentos = sql.SQL(", ").join(
        sql.SQL("{} => {}").format(sql.Identifier(p), sql.Placeholder(p)) for p in parametros
    )
    return sql.SQL("SELECT {}({})").format(sql.Identifier("core", nome), argumentos)


def chamar_funcao(con: Conexao, nome: str, /, **parametros: object) -> Any:
    """Chama uma função do schema core com parâmetros nomeados e devolve o resultado."""
    linha = con.execute(comando_funcao(nome, list(parametros)), parametros).fetchone()
    if linha is None:  # não acontece: SELECT de uma função sempre devolve uma linha
        raise RuntimeError(f"core.{nome} não devolveu resultado")
    return linha[0]
