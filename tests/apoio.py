"""Funções de apoio usadas pelos testes e pelas fixtures."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from almox.banco import Conexao

# Recife não tem horário de verão desde 2019: fuso fixo -03:00.
RECIFE = timezone(timedelta(hours=-3))
T0 = datetime(2026, 1, 5, 8, 0, tzinfo=RECIFE)


def horas(n: float) -> datetime:
    """Instante n horas depois de T0 (base de tempo dos testes)."""
    return T0 + timedelta(hours=n)


@contextmanager
def espera_erro(con: Conexao, sqlstate: str) -> Iterator[None]:
    """Exige que o bloco falhe no banco com o SQLSTATE informado.

    O bloco roda num savepoint: a falha desfaz só o bloco, e o teste pode continuar
    usando a conexão (sem o savepoint, a transação inteira ficaria abortada).
    """
    with pytest.raises(psycopg.Error) as info, con.transaction():
        yield
    assert info.value.sqlstate == sqlstate, (
        f"esperado {sqlstate}, veio {info.value.sqlstate}: {info.value}"
    )


def valor(con: Conexao, comando: str, parametros: dict[str, object] | None = None) -> object:
    """Primeira coluna da primeira linha."""
    linha = con.execute(comando, parametros).fetchone()
    assert linha is not None
    return linha[0]


@dataclass(frozen=True)
class CargaPadrao:
    """Resultado da carga do conjunto padrão no banco de testes (fixture carga_padrao)."""

    pasta: Path
    eventos: int
    linhas_planilha: int
    resultado: dict[str, float]
    manifesto: dict[str, object]
