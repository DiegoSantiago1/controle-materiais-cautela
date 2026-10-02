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
    "bi.dim_operador",
    "bi.fato_posse_atual",
    "bi.fato_estoque_atual",
    "bi.fato_unidade_atual",
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
    "SELECT count(*) FROM app.credencial",  # senhas e sessões da aplicação
    "SELECT count(*) FROM app.sessao",
    "SELECT count(*) FROM core.auditoria",
    "SELECT count(*) FROM core.vw_posse",
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


def test_bi_conecta_no_banco_da_aplicacao_so_para_ler_o_bi(banco_teste: ConfigBanco) -> None:
    """O relatório operacional lê o banco da aplicação (D27). Lá, o usuário do BI lê as
    views do bi e nada do core nem do app (senhas e sessões)."""
    from almox.config import carregar_config_banco

    config = carregar_config_banco().do_banco_da_aplicacao().como_bi()
    with conectar(config) as con:
        con.execute("SELECT count(*) FROM bi.dim_setor").fetchone()  # existe desde a 0011
        for tabela in ("app.credencial", "app.sessao", "core.movimentacao", "core.usuario"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), con.transaction():
                con.execute(f"SELECT 1 FROM {tabela} LIMIT 1")  # noqa: S608 (nome fixo)


def test_posse_atual_bate_com_o_estado(bd_bi_dono: Conexao) -> None:
    """Cada unidade CAUTELADA aparece uma vez na posse atual, e o estoque atual tem uma
    linha por material."""
    con = bd_bi_dono
    unidades = con.execute(
        "SELECT count(*) FROM core.unidade_patrimonial WHERE status = 'CAUTELADA'"
    ).fetchone()
    posse = con.execute("SELECT count(*), count(DISTINCT bmp) FROM bi.fato_posse_atual").fetchone()
    assert unidades is not None and posse is not None
    assert posse == (unidades[0], unidades[0])
    materiais = con.execute(
        "SELECT (SELECT count(*) FROM core.material_tipo), count(*) FROM bi.fato_estoque_atual"
    ).fetchone()
    assert materiais is not None and materiais[0] == materiais[1]


@pytest.fixture
def bd_bi_dono(bd: Conexao) -> Conexao:
    return bd
