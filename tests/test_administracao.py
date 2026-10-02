"""Administração pela aplicação (migração 0015): cadastros, auditoria e as funções app.*
que só rodam com sessão válida.

Tudo roda dentro da transação do teste (desfeita no fim). As funções app.* são chamadas
pelo dono do banco aqui; o teste de permissões do usuário da API está em test_aplicacao.
"""

import json
from datetime import date, timedelta

import pytest

from almox.banco import Conexao, chamar_funcao

from .apoio import abrir_sessao, espera_erro, valor
from .cenario import Base, criar_material, criar_unidades

pytestmark = pytest.mark.integracao


def _app(bd: Conexao, funcao: str, token: bytes, *argumentos: object) -> object:
    marcadores = ", ".join(["%s"] * (len(argumentos) + 1))
    comando = f"SELECT app.{funcao}({marcadores})"
    linha = bd.execute(comando, [token, *argumentos]).fetchone()
    assert linha is not None
    return linha[0]


def _auditoria(
    bd: Conexao, entidade: str, entidade_id: int
) -> list[tuple[str, int, dict[str, object]]]:
    return [
        (acao, executor, detalhe if isinstance(detalhe, dict) else json.loads(detalhe))
        for acao, executor, detalhe in bd.execute(
            "SELECT acao, executado_por, detalhe FROM core.auditoria "
            "WHERE entidade = %s AND entidade_id = %s ORDER BY id",
            [entidade, entidade_id],
        ).fetchall()
    ]


@pytest.fixture
def admin(bd: Conexao, base: Base) -> bytes:
    return abrir_sessao(bd, base.admin)


# ------------------------------------------------------------------ sessão
def test_quem_executa_vem_da_sessao(bd: Conexao, base: Base, admin: bytes) -> None:
    categoria = _app(bd, "cadastrar_categoria", admin, "Categoria da Sessão")
    assert isinstance(categoria, int)
    assert _auditoria(bd, "CATEGORIA", categoria) == [
        ("CADASTRAR", base.admin, {"nome": "Categoria da Sessão"})
    ]


@pytest.mark.parametrize("caso", ["inexistente", "vencida", "inativo"])
def test_sessao_invalida(bd: Conexao, base: Base, caso: str) -> None:
    token = {
        "inexistente": lambda: bytes(32),
        "vencida": lambda: abrir_sessao(bd, base.admin, "-1 second"),
        "inativo": lambda: abrir_sessao(bd, base.usuario_inativo),
    }[caso]()
    with espera_erro(bd, "ALM13"):
        _app(bd, "cadastrar_categoria", token, "Categoria Invasora")


def test_equipamentista_nao_administra(bd: Conexao, base: Base) -> None:
    token = abrir_sessao(bd, base.equipamentista)
    with espera_erro(bd, "ALM05"):
        _app(bd, "cadastrar_categoria", token, "Categoria do Equipamentista")


# ------------------------------------------------------------------ auditoria
@pytest.mark.parametrize(
    "comando",
    ["UPDATE core.auditoria SET acao = 'OUTRA'", "DELETE FROM core.auditoria",
     "TRUNCATE core.auditoria"],
)  # fmt: skip
def test_auditoria_imutavel(bd: Conexao, admin: bytes, comando: str) -> None:
    _app(bd, "cadastrar_categoria", admin, "Categoria Auditada")
    with espera_erro(bd, "ALM12"):
        bd.execute(comando)


# ------------------------------------------------------------------ categorias
def test_categoria_duplicada_sem_diferenciar_maiusculas(bd: Conexao, admin: bytes) -> None:
    _app(bd, "cadastrar_categoria", admin, "Paraquedismo Avançado")
    with espera_erro(bd, "ALM11"):
        _app(bd, "cadastrar_categoria", admin, "PARAQUEDISMO AVANÇADO")


@pytest.mark.parametrize("nome", ["", "   ", None])
def test_categoria_sem_nome(bd: Conexao, admin: bytes, nome: str | None) -> None:
    with espera_erro(bd, "ALM10"):
        _app(bd, "cadastrar_categoria", admin, nome)


def test_renomear_categoria_guarda_antes_e_depois(bd: Conexao, base: Base, admin: bytes) -> None:
    categoria = _app(bd, "cadastrar_categoria", admin, "Nome Antigo")
    _app(bd, "renomear_categoria", admin, categoria, "Nome Novo")
    assert _auditoria(bd, "CATEGORIA", categoria)[-1] == (  # type: ignore[arg-type]
        "RENOMEAR", base.admin, {"antes": "Nome Antigo", "depois": "Nome Novo"})  # fmt: skip


def test_renomear_categoria_inexistente(bd: Conexao, admin: bytes) -> None:
    with espera_erro(bd, "ALM09"):
        _app(bd, "renomear_categoria", admin, 2_000_000_000, "Qualquer")


def test_subcategoria(bd: Conexao, admin: bytes) -> None:
    categoria = _app(bd, "cadastrar_categoria", admin, "Comunicação Teste")
    sub = _app(bd, "cadastrar_subcategoria", admin, categoria, "Rádios")
    assert isinstance(sub, int)
    with espera_erro(bd, "ALM11"):
        _app(bd, "cadastrar_subcategoria", admin, categoria, "rádios")
    outra = _app(bd, "cadastrar_categoria", admin, "Outra Categoria Teste")
    _app(bd, "cadastrar_subcategoria", admin, outra, "Rádios")  # mesmo nome em outra categoria
    with espera_erro(bd, "ALM09"):
        _app(bd, "cadastrar_subcategoria", admin, 2_000_000_000, "Órfã")


# ------------------------------------------------------------------ materiais
def _cadastrar(
    bd: Conexao, admin: bytes, base: Base, nome: str, controle: str = "SERIAL", **extra: object
) -> object:
    parametros: dict[str, object] = {
        "unidade_medida": "UN",
        "prazo": 12 if controle == "SERIAL" else None,
        "minimo": None,
        "maximo": None,
        "local": None,
        "custo": 100,
        "descricao": None,
    }
    parametros.update(extra)
    sub = base.subcategoria_serial if controle == "SERIAL" else base.subcategoria_consumo
    return _app(bd, "cadastrar_material", admin, nome, sub, controle, *parametros.values())


def test_material_patrimonial_ganha_codigo_e_minimo(bd: Conexao, base: Base, admin: bytes) -> None:
    primeiro = _cadastrar(bd, admin, base, "Zabumba de Fanfarra", minimo=3)
    segundo = _cadastrar(bd, admin, base, "Zabumba Reserva")
    codigos = bd.execute(
        "SELECT codigo, estoque_minimo, controle FROM core.material_tipo WHERE id IN (%s, %s) "
        "ORDER BY id",
        [primeiro, segundo],
    ).fetchall()
    numero = int(codigos[0][0][4:])
    assert codigos == [
        (f"ZAB-{numero:04d}", 3, "SERIAL"),
        (f"ZAB-{numero + 1:04d}", None, "SERIAL"),
    ]


def test_codigo_sem_acento(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Ângulo de Prumo")
    codigo = valor(bd, "SELECT codigo FROM core.material_tipo WHERE id = %(m)s", {"m": material})
    assert str(codigo).startswith("ANG-")


def test_material_de_consumo_ganha_saldo(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(
        bd, admin, base, "Pilha AA Teste", "CONSUMO", unidade_medida="PCT", minimo=10,
        maximo=100, local=base.local,
    )  # fmt: skip
    saldo = bd.execute(
        "SELECT quantidade, estoque_minimo, estoque_maximo, local_id FROM core.saldo_consumo "
        "WHERE material_tipo_id = %s",
        [material],
    ).fetchone()
    assert saldo == (0, 10, 100, base.local)


@pytest.mark.parametrize(
    ("controle", "extra"),
    [
        ("SERIAL", {"unidade_medida": "CX"}),
        ("SERIAL", {"prazo": 0}),
        ("SERIAL", {"prazo": 8761}),
        ("SERIAL", {"custo": -1}),
        ("SERIAL", {"minimo": -1}),
        ("CONSUMO", {"prazo": 12, "minimo": 1, "maximo": 10}),
        ("CONSUMO", {"minimo": None, "maximo": 10}),
        ("CONSUMO", {"minimo": 20, "maximo": 10}),
        ("CONSUMO", {"minimo": 1, "maximo": 10, "unidade_medida": "XX"}),
        ("OUTRO", {}),
    ],
)
def test_material_invalido(
    bd: Conexao, base: Base, admin: bytes, controle: str, extra: dict[str, object]
) -> None:
    if controle == "CONSUMO":
        extra = {"local": base.local, **extra}
    with espera_erro(bd, "ALM10"):
        _cadastrar(bd, admin, base, "Material Inválido Teste", controle, **extra)


def test_material_de_consumo_sem_local(bd: Conexao, base: Base, admin: bytes) -> None:
    with espera_erro(bd, "ALM09"):
        _cadastrar(bd, admin, base, "Sem Local Teste", "CONSUMO", minimo=1, maximo=5)


def test_material_com_nome_repetido(bd: Conexao, base: Base, admin: bytes) -> None:
    _cadastrar(bd, admin, base, "Mosquetão de Aço")
    with espera_erro(bd, "ALM11"):
        _cadastrar(bd, admin, base, "MOSQUETÃO DE AÇO")


def test_atualizar_material_audita_so_o_que_mudou(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Lanterna Tática Teste", minimo=2)
    _app(bd, "atualizar_material", admin, material, "Lanterna Tática Teste",
         base.subcategoria_serial, 24, 5, 100, None, True)  # fmt: skip
    _, executor, detalhe = _auditoria(bd, "MATERIAL", material)[-1]  # type: ignore[arg-type]
    assert executor == base.admin
    assert detalhe == {
        "prazo_devolucao_horas": {"antes": 12, "depois": 24},
        "estoque_minimo": {"antes": 2, "depois": 5},
    }


def test_material_inativo_nao_recebe_unidades(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Material Descontinuado")
    _app(bd, "atualizar_material", admin, material, "Material Descontinuado",
         base.subcategoria_serial, 12, None, 100, None, False)  # fmt: skip
    with espera_erro(bd, "ALM02"):
        _app(bd, "entrada_lote", admin, material, 2, base.local, "BOM", None, None)


def test_atualizar_minimo_de_consumo_acima_do_maximo(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Fita Isolante Teste", "CONSUMO", unidade_medida="ROLO",
                          minimo=5, maximo=50, local=base.local)  # fmt: skip
    with espera_erro(bd, "ALM10"):
        _app(bd, "atualizar_material", admin, material, "Fita Isolante Teste",
             base.subcategoria_consumo, None, 51, 1, None, True)  # fmt: skip
    _app(bd, "atualizar_material", admin, material, "Fita Isolante Teste",
         base.subcategoria_consumo, None, 8, 1, None, True)  # fmt: skip
    assert valor(bd, "SELECT estoque_minimo FROM core.saldo_consumo WHERE material_tipo_id = %(m)s",
                 {"m": material}) == 8  # fmt: skip


# ------------------------------------------------------------------ entrada em lote
def test_entrada_em_lote_com_bmp_sequencial(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Barraca Teste Lote")
    maior = valor(bd, "SELECT max(bmp::integer) FROM core.unidade_patrimonial")
    ids = _app(bd, "entrada_lote", admin, material, 3, base.local, "BOM", None, "NF 123")
    assert isinstance(ids, list) and len(ids) == 3
    bmps = bd.execute(
        "SELECT bmp::integer FROM core.unidade_patrimonial WHERE id = ANY(%s) ORDER BY 1", [ids]
    ).fetchall()
    inicio = int(maior or 999999) + 1  # type: ignore[call-overload]
    assert [b for (b,) in bmps] == [inicio, inicio + 1, inicio + 2]
    documentos = bd.execute(
        "SELECT DISTINCT documento_ref FROM core.movimentacao WHERE unidade_id = ANY(%s)", [ids]
    ).fetchall()
    assert documentos == [("NF 123",)]


def test_entrada_avariada_vai_para_manutencao(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Rádio Chegou Quebrado")
    with espera_erro(bd, "ALM10"):
        _app(bd, "entrada_lote", admin, material, 1, base.local, "AVARIADO", None, None)
    ids = _app(bd, "entrada_lote", admin, material, 1, base.local, "AVARIADO", "Tela trincada",
               None)  # fmt: skip
    assert valor(bd, "SELECT status FROM core.unidade_patrimonial WHERE id = %(u)s",
                 {"u": ids[0]}) == "EM_MANUTENCAO"  # type: ignore[index]  # fmt: skip


@pytest.mark.parametrize("quantidade", [0, 501, None])
def test_entrada_com_quantidade_invalida(
    bd: Conexao, base: Base, admin: bytes, quantidade: int | None
) -> None:
    material = _cadastrar(bd, admin, base, "Material Quantidade Teste")
    with espera_erro(bd, "ALM10"):
        _app(bd, "entrada_lote", admin, material, quantidade, base.local, "BOM", None, None)


def test_entrada_em_local_inexistente(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Material Local Teste")
    with espera_erro(bd, "ALM09"):
        _app(bd, "entrada_lote", admin, material, 1, 2_000_000_000, "BOM", None, None)


def test_equipamentista_nao_da_entrada(bd: Conexao, base: Base, admin: bytes) -> None:
    material = _cadastrar(bd, admin, base, "Material Sem Entrada Teste")
    token = abrir_sessao(bd, base.equipamentista)
    with espera_erro(bd, "ALM05"):
        _app(bd, "entrada_lote", token, material, 1, base.local, "BOM", None, None)


# ------------------------------------------------------------------ militares
def _cadastrar_pessoa(
    bd: Conexao, admin: bytes, base: Base, matricula: str, guerra: str, **extra: object
) -> object:
    dados: dict[str, object] = {
        "nome": f"Militar {guerra}",
        "posto": "SGT",
        "setor": base.setor,
        "entrada": None,
    }
    dados.update(extra)
    return _app(bd, "cadastrar_pessoa", admin, matricula, dados["nome"], guerra, dados["posto"],
                dados["setor"], dados["entrada"])  # fmt: skip


def test_cadastrar_militar(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000001", "Teste Novo")
    linha = bd.execute(
        "SELECT posto_graduacao, nome_guerra, data_entrada, data_saida FROM core.pessoa "
        "WHERE id = %s",
        [pessoa],
    ).fetchone()
    hoje = valor(bd, "SELECT core.data_local(now())")
    assert linha == ("SGT", "Teste Novo", hoje, None)
    assert _auditoria(bd, "PESSOA", pessoa)[0][0] == "CADASTRAR"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("matricula", "guerra", "extra", "sqlstate"),
    [
        ("123", "Teste A", {}, "ALM10"),
        ("12345678", "Teste B", {}, "ALM10"),
        ("4000002", "", {}, "ALM10"),
        ("4000003", "x" * 31, {}, "ALM10"),
        ("4000004", "Teste C", {"posto": "3S"}, "ALM10"),
        ("4000005", "Teste D", {"setor": 2_000_000_000}, "ALM09"),
        ("4000006", "Teste E", {"nome": "  "}, "ALM10"),
        ("4000007", "Teste F", {"entrada": date.today() + timedelta(days=30)}, "ALM10"),
    ],
)
def test_militar_invalido(
    bd: Conexao, base: Base, admin: bytes, matricula: str, guerra: str,
    extra: dict[str, object], sqlstate: str,
) -> None:  # fmt: skip
    with espera_erro(bd, sqlstate):
        _cadastrar_pessoa(bd, admin, base, matricula, guerra, **extra)


def test_matricula_e_nome_de_guerra_repetidos(bd: Conexao, base: Base, admin: bytes) -> None:
    _cadastrar_pessoa(bd, admin, base, "4000010", "Teste Repetido")
    with espera_erro(bd, "ALM11"):
        _cadastrar_pessoa(bd, admin, base, "4000010", "Outro Nome")
    with espera_erro(bd, "ALM11"):
        _cadastrar_pessoa(bd, admin, base, "4000011", "TESTE REPETIDO")


def test_atualizar_militar(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000020", "Teste Promovido", posto="CB")
    _app(bd, "atualizar_pessoa", admin, pessoa, "Militar Teste Promovido", "Teste Promovido",
         "SGT", base.setor)  # fmt: skip
    assert _auditoria(bd, "PESSOA", pessoa)[-1][2] == {  # type: ignore[arg-type]
        "posto": {"antes": "CB", "depois": "SGT"}}  # fmt: skip


def test_saida_com_material_em_posse_e_recusada(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000030", "Teste Com Posse")
    material = criar_material(bd, base, "SERIAL", prazo_horas=12)
    unidade = criar_unidades(bd, base, material, 1)
    chamar_funcao(bd, "registrar_retirada_lote", p_material_tipo_id=material, p_quantidade=None,
                  p_pessoa_id=pessoa, p_executado_por=base.equipamentista,
                  p_unidades=unidade)  # fmt: skip
    with espera_erro(bd, "ALM02"):
        _app(bd, "registrar_saida_pessoa", admin, pessoa, date.today())


def test_saida_desativa_o_usuario_e_derruba_as_sessoes(
    bd: Conexao, base: Base, admin: bytes
) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000040", "Teste Saindo")
    usuario = _app(bd, "cadastrar_usuario", admin, pessoa, "teste.saindo", "EQUIPAMENTISTA")
    abrir_sessao(bd, usuario)  # type: ignore[arg-type]
    _app(bd, "registrar_saida_pessoa", admin, pessoa, date.today())
    assert valor(bd, "SELECT ativo FROM core.usuario WHERE id = %(u)s", {"u": usuario}) is False
    assert valor(bd, "SELECT count(*) FROM app.sessao WHERE usuario_id = %(u)s",
                 {"u": usuario}) == 0  # fmt: skip
    with espera_erro(bd, "ALM02"):  # já saiu
        _app(bd, "registrar_saida_pessoa", admin, pessoa, date.today())


def test_saida_antes_da_entrada(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000050", "Teste Data")
    with espera_erro(bd, "ALM10"):
        _app(bd, "registrar_saida_pessoa", admin, pessoa, date(2000, 1, 1))


def test_ninguem_registra_a_propria_saida(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = valor(bd, "SELECT pessoa_id FROM core.usuario WHERE id = %(u)s", {"u": base.admin})
    with espera_erro(bd, "ALM10"):
        _app(bd, "registrar_saida_pessoa", admin, pessoa, date.today())


# ------------------------------------------------------------------ usuários
def test_cadastrar_usuario(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000060", "Teste Usuário")
    usuario = _app(bd, "cadastrar_usuario", admin, pessoa, "Teste.Usuario", "EQUIPAMENTISTA")
    linha = bd.execute("SELECT login, perfil, ativo FROM core.usuario WHERE id = %s", [usuario])
    assert linha.fetchone() == ("teste.usuario", "EQUIPAMENTISTA", True)  # login em minúsculas
    with espera_erro(bd, "ALM11"):  # um usuário por militar
        _app(bd, "cadastrar_usuario", admin, pessoa, "outro.login", "CONSULTA")


@pytest.mark.parametrize(
    ("login", "perfil", "sqlstate"),
    [
        ("ab", "CONSULTA", "ALM10"),
        ("1abc", "CONSULTA", "ALM10"),
        ("tem espaco", "CONSULTA", "ALM10"),
        ("valido.um", "SUPERUSUARIO", "ALM10"),
        ("valido.dois", None, "ALM10"),
    ],
)
def test_usuario_invalido(
    bd: Conexao, base: Base, admin: bytes, login: str, perfil: str | None, sqlstate: str
) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000070", "Teste Login")
    with espera_erro(bd, sqlstate):
        _app(bd, "cadastrar_usuario", admin, pessoa, login, perfil)


def test_login_repetido(bd: Conexao, base: Base, admin: bytes) -> None:
    a = _cadastrar_pessoa(bd, admin, base, "4000080", "Teste Login A")
    b = _cadastrar_pessoa(bd, admin, base, "4000081", "Teste Login B")
    _app(bd, "cadastrar_usuario", admin, a, "login.repetido", "CONSULTA")
    with espera_erro(bd, "ALM11"):
        _app(bd, "cadastrar_usuario", admin, b, "LOGIN.REPETIDO", "CONSULTA")


def test_usuario_para_quem_ja_saiu(bd: Conexao, base: Base, admin: bytes) -> None:
    with espera_erro(bd, "ALM03"):
        _app(bd, "cadastrar_usuario", admin, base.pessoa_transferida, "teste.saiu", "CONSULTA")


def test_mudar_perfil_derruba_as_sessoes(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000090", "Teste Perfil")
    usuario = _app(bd, "cadastrar_usuario", admin, pessoa, "teste.perfil", "EQUIPAMENTISTA")
    token = abrir_sessao(bd, usuario)  # type: ignore[arg-type]
    _app(bd, "alterar_usuario", admin, usuario, "CONSULTA", True)
    with espera_erro(bd, "ALM13"):  # a sessão antiga não vale mais
        _app(bd, "retirar", token, 1, 1, 1, None, "BOM", None, None, None)
    assert _auditoria(bd, "USUARIO", usuario)[-1][2] == {  # type: ignore[arg-type]
        "perfil": {"antes": "EQUIPAMENTISTA", "depois": "CONSULTA"},
        "ativo": {"antes": True, "depois": True},
    }


@pytest.mark.parametrize(("perfil", "ativo"), [("EQUIPAMENTISTA", True), ("ADMINISTRADOR", False)])
def test_ninguem_tira_o_proprio_acesso(
    bd: Conexao, base: Base, admin: bytes, perfil: str, ativo: bool
) -> None:
    with espera_erro(bd, "ALM10"):
        _app(bd, "alterar_usuario", admin, base.admin, perfil, ativo)


def test_sempre_sobra_um_administrador(bd: Conexao, base: Base) -> None:
    """A trava de último administrador. Pelas funções, ela só é alcançada com duas
    alterações simultâneas (A rebaixa B enquanto B rebaixa A); aqui o estado é montado à
    mão, dentro da transação do teste, e a verificação é chamada direto."""
    bd.execute("UPDATE core.usuario SET ativo = false WHERE perfil = 'ADMINISTRADOR'")
    with espera_erro(bd, "ALM02"):
        bd.execute("SELECT core._exigir_um_administrador_ativo()")


def test_reativar_usuario_de_quem_saiu(bd: Conexao, base: Base, admin: bytes) -> None:
    pessoa = _cadastrar_pessoa(bd, admin, base, "4000100", "Teste Reativar")
    usuario = _app(bd, "cadastrar_usuario", admin, pessoa, "teste.reativar", "CONSULTA")
    _app(bd, "registrar_saida_pessoa", admin, pessoa, date.today())
    with espera_erro(bd, "ALM03"):
        _app(bd, "alterar_usuario", admin, usuario, "CONSULTA", True)


# ------------------------------------------------------------------ senhas
HASH = "scrypt$131072$8$1$" + "A" * 22 + "$" + "B" * 43


def test_definir_senha_encerra_as_sessoes_do_usuario(bd: Conexao, base: Base, admin: bytes) -> None:
    abrir_sessao(bd, base.equipamentista)
    _app(bd, "definir_senha", admin, base.equipamentista, HASH)
    assert valor(bd, "SELECT senha_hash FROM app.credencial WHERE usuario_id = %(u)s",
                 {"u": base.equipamentista}) == HASH  # fmt: skip
    assert valor(bd, "SELECT count(*) FROM app.sessao WHERE usuario_id = %(u)s",
                 {"u": base.equipamentista}) == 0  # fmt: skip


def test_senha_em_texto_puro_e_recusada(bd: Conexao, base: Base, admin: bytes) -> None:
    with espera_erro(bd, "23514"):
        _app(bd, "definir_senha", admin, base.equipamentista, "1234567890")


def test_equipamentista_nao_define_senha_de_outro(bd: Conexao, base: Base) -> None:
    token = abrir_sessao(bd, base.equipamentista)
    with espera_erro(bd, "ALM05"):
        _app(bd, "definir_senha", token, base.admin, HASH)


def test_trocar_a_propria_senha_mantem_a_sessao_atual(bd: Conexao, base: Base) -> None:
    atual = abrir_sessao(bd, base.equipamentista)
    outra = abrir_sessao(bd, base.equipamentista)
    _app(bd, "trocar_minha_senha", atual, HASH)
    sessoes = bd.execute(
        "SELECT token_hash FROM app.sessao WHERE usuario_id = %s", [base.equipamentista]
    ).fetchall()
    assert [bytes(t) for (t,) in sessoes] == [atual]
    assert outra != atual
