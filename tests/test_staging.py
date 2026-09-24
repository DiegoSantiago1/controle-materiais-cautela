"""O staging aceita qualquer texto: é ali que os erros da planilha precisam caber."""

import pytest

from almox.banco import Conexao

from .apoio import espera_erro, valor

pytestmark = pytest.mark.integracao

# Número de linha que nenhum arquivo real usa: o teste de carga confirma uma planilha
# de verdade (linhas 1..N) no mesmo banco, e os testes não podem depender da ordem.
LINHA_DE_TESTE = 900_001


def test_staging_aceita_linha_com_dados_sujos(bd: Conexao) -> None:
    sujos = {
        "linha": LINHA_DE_TESTE,
        "bmp": "81O0234",  # letra O no lugar de zero
        "nomenclatura": "  RADIO PORT. VHF  ",
        "numero_serie": "",
        "local": "dep.central",
        "situacao": "descarga???",
        "observacao": "<b>verificar</b>",
    }
    bd.execute(
        "INSERT INTO staging.carga_planilha (linha, bmp, nomenclatura, numero_serie, local, "
        "situacao, observacao, arquivo) VALUES (%(linha)s, %(bmp)s, %(nomenclatura)s, "
        "%(numero_serie)s, %(local)s, %(situacao)s, %(observacao)s, 'teste.csv')",
        sujos,
    )
    assert (
        valor(
            bd, "SELECT bmp FROM staging.carga_planilha WHERE linha = %(l)s", {"l": LINHA_DE_TESTE}
        )
        == "81O0234"
    )


def test_numero_da_linha_nao_se_repete(bd: Conexao) -> None:
    bd.execute(
        "INSERT INTO staging.carga_planilha (linha, arquivo) VALUES (%s, 'a.csv')", [LINHA_DE_TESTE]
    )
    with espera_erro(bd, "23505"):
        bd.execute(
            "INSERT INTO staging.carga_planilha (linha, arquivo) VALUES (%s, 'a.csv')",
            [LINHA_DE_TESTE],
        )
