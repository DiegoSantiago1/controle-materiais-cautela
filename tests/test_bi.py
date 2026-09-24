"""V1 — o usuário do Power BI lê o modelo estrela e as análises, e nada além disso."""

import psycopg
import pytest

from almox.banco import Conexao, conectar
from almox.config import ConfigBanco

pytestmark = pytest.mark.integracao

LEGIVEIS = [
    "bi.dim_calendario",
    "bi.dim_setor",
    "bi.dim_pessoa",
    "bi.dim_material",
    "bi.fato_movimentacao",
    "bi.fato_cautela",
    "bi.fato_consumo_diario",
    "analise.vw_uso_material",
    "analise.vw_status_consumo",
    "analise.vw_atraso_pessoa",
    "analise.vw_ruptura",
    "dq.vw_ultima_execucao",
]

PROIBIDOS = [
    "SELECT count(*) FROM core.movimentacao",  # tabelas do core
    "SELECT count(*) FROM core.pessoa",
    "SELECT count(*) FROM staging.carga_planilha",  # dados crus
    "SELECT count(*) FROM staging.gabarito_erro",
    "DELETE FROM dq.regra",  # escrever
    "INSERT INTO analise.abreviacao VALUES ('X', 'Y')",
    "CREATE TABLE bi.intrusa (a int)",  # criar objetos
    "CREATE TABLE public.intrusa (a int)",
    "SELECT core.registrar_entrada_consumo(1, 1, 1)",  # funções de escrita
    "SELECT core.estornar_movimentacao(1, 1, 'x')",
    "SELECT dq.executar()",
]


@pytest.fixture
def bi(banco_teste: ConfigBanco) -> Conexao:
    con = conectar(banco_teste.como_bi())
    con.autocommit = True
    return con


def test_conecta_como_usuario_do_bi(bi: Conexao, banco_teste: ConfigBanco) -> None:
    with bi:
        linha = bi.execute("SELECT current_user, pg_has_role('almox_leitura', 'member')").fetchone()
    assert linha == (banco_teste.usuario_bi, True)


@pytest.mark.parametrize("objeto", LEGIVEIS)
def test_bi_le_o_modelo_e_as_analises(bi: Conexao, objeto: str) -> None:
    with bi:
        bi.execute(f"SELECT * FROM {objeto} LIMIT 1")  # noqa: S608 (nome fixo do teste)


@pytest.mark.parametrize("comando", PROIBIDOS)
def test_bi_nao_le_o_core_nem_escreve(bi: Conexao, comando: str) -> None:
    with bi, pytest.raises(psycopg.errors.InsufficientPrivilege):
        bi.execute(comando)


def test_calendario_cobre_um_ano_ate_a_referencia(bi: Conexao) -> None:
    with bi:
        linha = bi.execute(
            "SELECT count(*), max(data) - min(data), count(*) FILTER (WHERE dia_util) "
            "FROM bi.dim_calendario"
        ).fetchone()
    assert linha is not None
    dias, amplitude, uteis = linha
    assert (dias, amplitude) == (365, 364)
    assert 259 <= uteis <= 262  # 52 semanas de 5 dias + 1 ou 2 dias
