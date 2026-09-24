"""Linhas de comando com o banco fora do ar: mensagem clara e código de saída 1, rápido.

Regressão: a recriação do schema passa pelo Alembic (SQLAlchemy), que embrulha o erro do
psycopg em sqlalchemy.exc.OperationalError. A carga só pegava o do psycopg: com o banco
fora do ar, esperava mais de 2 minutos (sem connect_timeout no Alembic) e terminava num
traceback.
"""

import time
from collections.abc import Callable

import pytest

from almox import carga, migracoes

pytestmark = pytest.mark.integracao

PORTA_SEM_BANCO = "5499"


@pytest.mark.parametrize(
    ("principal", "argumentos"),
    [
        (carga.main, ["--recriar", "--banco", "app"]),
        (migracoes.main, ["teste"]),
    ],
    ids=["carga", "migracoes"],
)
def test_banco_fora_do_ar_da_erro_claro_e_rapido(
    principal: Callable[[list[str]], int],
    argumentos: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ALMOX_DB_PORT", PORTA_SEM_BANCO)
    inicio = time.monotonic()
    assert principal(argumentos) == 1
    assert time.monotonic() - inicio < 20
    assert "banco inacessível" in capsys.readouterr().err
