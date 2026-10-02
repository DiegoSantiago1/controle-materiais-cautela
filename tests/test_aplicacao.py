"""P3.1 — o usuário da API movimenta só pelas funções de regra, e nada além disso.

A prova é feita conectando de verdade como o usuário da aplicação (grupo almox_aplicacao)
e tentando cada operação proibida: o banco precisa recusar com "permission denied"
(InsufficientPrivilege), não importa o que a API mande.

Desde a migração 0015 a API só executa as funções app.*, que recebem o hash do token da
sessão: quem executa é o dono da sessão, e não um id que a API informe.
"""

from collections.abc import Callable, Iterator

import psycopg
import pytest

from almox.banco import Conexao, conectar
from almox.config import ConfigBanco

from .apoio import abrir_sessao, valor
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
    # funções do core: a API só chama as app.*, que exigem sessão
    "SELECT core.registrar_retirada_unidade(1, 1, 1)",
    "SELECT core.registrar_devolucao_unidade(1, 1, 1)",
    "SELECT core.registrar_retirada_lote(1, 1, 1, 1)",
    "SELECT core.registrar_devolucao_lote(ARRAY[1], 1, 1)",
    "SELECT core.cadastrar_usuario(1, 'intruso', 'ADMINISTRADOR', 1)",
    "SELECT core.alterar_usuario(1, 'ADMINISTRADOR', true, 1)",
    "SELECT core.registrar_entrada_consumo(1, 1, 1)",
    "SELECT core.estornar_movimentacao(1, 1, 'x')",
    "SELECT core.alterar_status_unidade(1, 'BAIXADA', 1, 'x')",
    "SELECT core.registrar_entrada_unidade(1, 1, 1)",
    # funções auxiliares (internas das regras)
    "SELECT core._exigir_perfil(1, ARRAY['ADMINISTRADOR'])",
    "SELECT app._usuario(decode('00', 'hex'))",
    "SELECT core._auditar(1, 'X', 'MATERIAL', 1)",
    # mexer na auditoria
    "INSERT INTO core.auditoria (executado_por, acao, entidade, entidade_id) "
    "VALUES (1, 'FALSA', 'MATERIAL', 1)",
    "DELETE FROM core.auditoria",
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


@pytest.fixture
def sessao(banco_teste: ConfigBanco) -> Callable[..., bytes]:
    """Abre (e confirma) sessões no banco, como o login da API faria."""

    def abrir(usuario: int, validade: str = "1 hour") -> bytes:
        with conectar(banco_teste) as con:
            return abrir_sessao(con, usuario, validade)

    return abrir


def test_movimenta_pelas_funcoes_da_aplicacao(
    api: Conexao, base: Base, unidade_livre: int, sessao: Callable[..., bytes]
) -> None:
    """Sem nenhum direito de escrita nas tabelas, a retirada e a devolução funcionam: as
    funções são SECURITY DEFINER e gravam com os direitos do dono. Quem executa sai da
    sessão, e não de um parâmetro."""
    token = sessao(base.equipamentista)
    material = valor(
        api,
        "SELECT material_tipo_id FROM core.unidade_patrimonial WHERE id = %(u)s",
        {"u": unidade_livre},
    )
    api.execute(
        "SELECT app.retirar(%s, %s, NULL, %s, NULL, 'BOM', NULL, NULL, %s)",
        (token, material, base.pessoa, [unidade_livre]),
    )
    status = valor(
        api, "SELECT status FROM core.unidade_patrimonial WHERE id = %(u)s", {"u": unidade_livre}
    )
    assert status == "CAUTELADA"
    api.execute(
        "SELECT app.devolver(%s, %s, %s, 'BOM', NULL, NULL)",
        (token, [unidade_livre], base.pessoa),
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


def test_regras_continuam_valendo_pela_api(
    api: Conexao, base: Base, unidade_livre: int, sessao: Callable[..., bytes]
) -> None:
    """SECURITY DEFINER dá direito de gravar, não de pular regra: o perfil CONSULTA
    continua sem poder retirar (ALM05)."""
    material = valor(
        api,
        "SELECT material_tipo_id FROM core.unidade_patrimonial WHERE id = %(u)s",
        {"u": unidade_livre},
    )
    with pytest.raises(psycopg.Error) as erro:
        api.execute(
            "SELECT app.retirar(%s, %s, NULL, %s, NULL, 'BOM', NULL, NULL, %s)",
            (sessao(base.consulta), material, base.pessoa, [unidade_livre]),
        )
    assert erro.value.sqlstate == "ALM05"


@pytest.mark.parametrize("caso", ["inexistente", "vencida", "usuario_inativo"])
def test_sem_sessao_valida_nada_e_executado(
    api: Conexao, base: Base, sessao: Callable[..., bytes], caso: str
) -> None:
    """O ataque que a 0015 fecha: com acesso ao banco como a API, alguém tenta agir como
    administrador. Sem o token de uma sessão válida de administrador, não há como."""
    if caso == "inexistente":
        token = bytes(32)
    elif caso == "vencida":
        token = sessao(base.admin, "-1 minute")
    else:
        token = sessao(base.usuario_inativo)
    with pytest.raises(psycopg.Error) as erro:
        api.execute("SELECT app.cadastrar_categoria(%s, 'Categoria do invasor')", (token,))
    assert erro.value.sqlstate == "ALM13"


def test_funcao_de_administrador_com_sessao_de_equipamentista(
    api: Conexao, base: Base, sessao: Callable[..., bytes]
) -> None:
    """Promover a si mesmo: recusado pela regra de perfil, mesmo com sessão válida."""
    with pytest.raises(psycopg.Error) as erro:
        api.execute(
            "SELECT app.alterar_usuario(%s, %s, 'ADMINISTRADOR', true)",
            (sessao(base.equipamentista), base.equipamentista),
        )
    assert erro.value.sqlstate == "ALM05"


FUNCOES_DEFINER = {
    # movimentação (0004, 0012, 0014)
    "core.registrar_entrada_unidade", "core.registrar_retirada_unidade",
    "core.registrar_devolucao_unidade", "core.alterar_status_unidade",
    "core.cadastrar_saldo_consumo", "core.registrar_entrada_consumo",
    "core.registrar_retirada_consumo", "core.registrar_ajuste_consumo",
    "core.estornar_movimentacao", "core.registrar_retirada_lote", "core.registrar_devolucao_lote",
    # administração (0015)
    "core.cadastrar_categoria", "core.renomear_categoria", "core.cadastrar_subcategoria",
    "core.renomear_subcategoria", "core.cadastrar_material", "core.atualizar_material",
    "core.registrar_entrada_lote", "core.cadastrar_pessoa", "core.atualizar_pessoa",
    "core.registrar_saida_pessoa", "core.cadastrar_usuario", "core.alterar_usuario",
    # aplicação, com sessão (0015)
    "app._usuario", "app.retirar", "app.devolver", "app.entrada_lote", "app.entrada_consumo",
    "app.ajustar_consumo", "app.alterar_status_unidade", "app.cadastrar_categoria",
    "app.renomear_categoria", "app.cadastrar_subcategoria", "app.renomear_subcategoria",
    "app.cadastrar_material", "app.atualizar_material", "app.cadastrar_pessoa",
    "app.atualizar_pessoa", "app.registrar_saida_pessoa", "app.cadastrar_usuario",
    "app.alterar_usuario", "app.definir_senha", "app.trocar_minha_senha",
}  # fmt: skip


def test_funcoes_de_escrita_tem_search_path_fixo(api: Conexao) -> None:
    """Toda função SECURITY DEFINER precisa de search_path fixo; sem ele, quem chama
    poderia criar um objeto com o mesmo nome num schema seu e desviar a função. A lista é
    exata: uma função nova com SECURITY DEFINER precisa entrar aqui de propósito."""
    linhas = api.execute(
        """
        SELECT n.nspname || '.' || p.proname, p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('core', 'app') AND p.prosecdef
        """
    ).fetchall()
    assert {nome for nome, _ in linhas} == FUNCOES_DEFINER
    assert all(config == ["search_path=pg_catalog, pg_temp"] for _, config in linhas)


def test_api_executa_so_as_funcoes_da_aplicacao(api: Conexao) -> None:
    """Das funções que gravam, a API só executa as app.* (menos a interna _usuario)."""
    linhas = api.execute(
        """
        SELECT n.nspname || '.' || p.proname
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('core', 'app') AND p.prosecdef
          AND has_function_privilege(p.oid, 'EXECUTE')
        """
    ).fetchall()
    executaveis = {nome for (nome,) in linhas}
    assert executaveis == {f for f in FUNCOES_DEFINER if f.startswith("app.")} - {"app._usuario"}


def test_formato_da_senha_e_imposto_pelo_banco(banco_teste: ConfigBanco, base: Base) -> None:
    """Nem o dono do banco grava senha em texto puro por engano."""
    with conectar(banco_teste) as con, pytest.raises(psycopg.errors.CheckViolation):
        con.execute(
            "INSERT INTO app.credencial (usuario_id, senha_hash) VALUES (%s, 'minhasenha123')",
            (base.equipamentista,),
        )
