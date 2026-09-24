"""P3.1 — o usuário da API movimenta só pelas funções de regra, e nada além disso.

A prova é feita conectando de verdade como o usuário da aplicação (grupo almox_aplicacao)
e tentando cada operação proibida: o banco precisa recusar com "permission denied"
(InsufficientPrivilege), não importa o que a API mande.
"""

from collections.abc import Iterator

import psycopg
import pytest

from almox.banco import Conexao, conectar
from almox.config import ConfigBanco

from .apoio import valor
from .cenario import Base, criar_material, criar_unidades

pytestmark = pytest.mark.integracao

# Operações que o usuário da API NUNCA pode fazer.
PROIBIDOS = [
    # gravar direto no histórico ou no estado (pulando as regras)
    "INSERT INTO core.movimentacao (ocorrida_em, tipo, material_tipo_id, controle, "
    "executado_por) VALUES (now(), 'ENTRADA', 1, 'SERIAL', 1)",
    "UPDATE core.unidade_patrimonial SET status = 'DISPONIVEL', detentor_id = NULL",
    "DELETE FROM core.pessoa",
    "UPDATE core.usuario SET perfil = 'ADMINISTRADOR'",  # promover a si mesmo
    "UPDATE core.saldo_consumo SET quantidade = 999",
    "TRUNCATE core.setor",
    # trocar senhas
    "UPDATE app.credencial SET senha_hash = 'x'",
    "INSERT INTO app.credencial (usuario_id, senha_hash) VALUES (1, 'x')",
    # ler o que não precisa (dados crus, análises)
    "SELECT count(*) FROM staging.carga_planilha",
    "SELECT count(*) FROM analise.vw_cautela",
    "SELECT count(*) FROM bi.fato_movimentacao",
    "SELECT count(*) FROM dq.ocorrencia",
    # funções de escrita que a tela não usa
    "SELECT core.registrar_entrada_consumo(1, 1, 1)",
    "SELECT core.estornar_movimentacao(1, 1, 'x')",
    "SELECT core.alterar_status_unidade(1, 'BAIXADA', 1, 'x')",
    "SELECT core.registrar_entrada_unidade(1, 1, 1)",
    # funções auxiliares (internas das regras)
    "SELECT core._exigir_perfil(1, ARRAY['ADMINISTRADOR'])",
    # criar objetos
    "CREATE TABLE core.intrusa (a int)",
    "CREATE TABLE public.intrusa (a int)",
    "CREATE FUNCTION app.intrusa() RETURNS int LANGUAGE sql AS 'SELECT 1'",
]


@pytest.fixture
def api(banco_teste: ConfigBanco) -> Iterator[Conexao]:
    con = conectar(banco_teste.como_aplicacao())
    con.autocommit = True
    try:
        yield con
    finally:
        con.close()


def test_conecta_como_usuario_da_aplicacao(api: Conexao, banco_teste: ConfigBanco) -> None:
    linha = api.execute(
        "SELECT current_user, pg_has_role('almox_aplicacao', 'member'), "
        "pg_has_role('almox_leitura', 'member')"
    ).fetchone()
    assert linha == (banco_teste.usuario_app, True, False)


def test_nao_conecta_no_banco_das_analises(config_banco: ConfigBanco) -> None:
    """A aplicação nunca toca o banco congelado que os notebooks e o Power BI leem."""
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        conectar(config_banco.como_aplicacao())


def test_nenhuma_escrita_direta_em_tabela_do_core(api: Conexao) -> None:
    """Varre TODAS as tabelas do core, inclusive as que forem criadas no futuro."""
    linhas = api.execute(
        """
        SELECT c.relname, p.privilegio
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN unnest(ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS p(privilegio)
        WHERE n.nspname = 'core' AND c.relkind IN ('r', 'p', 'v')
          AND has_table_privilege(c.oid, p.privilegio)
        """
    ).fetchall()
    assert linhas == []


@pytest.mark.parametrize("comando", PROIBIDOS)
def test_operacao_proibida_e_recusada_pelo_banco(api: Conexao, comando: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        api.execute(comando)


def test_sessao_so_insere_le_e_apaga(api: Conexao) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        api.execute("UPDATE app.sessao SET expira_em = expira_em + interval '1 year'")


@pytest.fixture
def unidade_livre(banco_teste: ConfigBanco, base: Base) -> int:
    """Uma unidade DISPONIVEL confirmada no banco (a conexão da API não vê transação alheia)."""
    with conectar(banco_teste) as con:
        return criar_unidades(con, base, criar_material(con, base, "SERIAL", prazo_horas=4))[0]


def test_movimenta_pelas_funcoes_de_regra(api: Conexao, base: Base, unidade_livre: int) -> None:
    """Sem nenhum direito de escrita nas tabelas, a retirada e a devolução funcionam:
    as funções são SECURITY DEFINER e gravam com os direitos do dono."""
    api.execute(
        "SELECT core.registrar_retirada_unidade(p_unidade_id => %s, p_pessoa_id => %s, "
        "p_executado_por => %s)",
        (unidade_livre, base.pessoa, base.equipamentista),
    )
    status = valor(
        api, "SELECT status FROM core.unidade_patrimonial WHERE id = %(u)s", {"u": unidade_livre}
    )
    assert status == "CAUTELADA"
    api.execute(
        "SELECT core.registrar_devolucao_unidade(p_unidade_id => %s, p_pessoa_id => %s, "
        "p_executado_por => %s)",
        (unidade_livre, base.pessoa, base.equipamentista),
    )
    tipos = api.execute(
        "SELECT tipo, executado_por FROM core.movimentacao WHERE unidade_id = %s ORDER BY id",
        (unidade_livre,),
    ).fetchall()
    assert tipos == [
        ("ENTRADA", base.estoquista),
        ("RETIRADA", base.equipamentista),
        ("DEVOLUCAO", base.equipamentista),
    ]


def test_regras_continuam_valendo_pela_api(api: Conexao, base: Base, unidade_livre: int) -> None:
    """SECURITY DEFINER dá direito de gravar, não de pular regra: o perfil CONSULTA
    continua sem poder retirar (ALM05)."""
    with pytest.raises(psycopg.Error) as erro:
        api.execute(
            "SELECT core.registrar_retirada_unidade(p_unidade_id => %s, p_pessoa_id => %s, "
            "p_executado_por => %s)",
            (unidade_livre, base.pessoa, base.consulta),
        )
    assert erro.value.sqlstate == "ALM05"


def test_funcoes_de_escrita_tem_search_path_fixo(api: Conexao) -> None:
    """Toda função SECURITY DEFINER do core precisa de search_path fixo; sem ele, quem
    chama poderia criar um objeto com o mesmo nome num schema seu e desviar a função."""
    linhas = api.execute(
        """
        SELECT p.proname, p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'core' AND p.prosecdef
        ORDER BY 1
        """
    ).fetchall()
    assert len(linhas) == 9
    assert all(config == ["search_path=pg_catalog, pg_temp"] for _, config in linhas)


def test_formato_da_senha_e_imposto_pelo_banco(banco_teste: ConfigBanco, base: Base) -> None:
    """Nem o dono do banco grava senha em texto puro por engano."""
    with conectar(banco_teste) as con, pytest.raises(psycopg.errors.CheckViolation):
        con.execute(
            "INSERT INTO app.credencial (usuario_id, senha_hash) VALUES (%s, 'minhasenha123')",
            (base.equipamentista,),
        )
