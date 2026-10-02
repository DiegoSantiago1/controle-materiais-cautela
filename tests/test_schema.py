"""Integridade garantida pelo banco: cada regra é testada tentando quebrá-la.

Os INSERTs aqui vão direto nas tabelas, sem passar pelas funções de movimentação. É a
prova de que o banco se defende sozinho, mesmo contra um cliente com defeito.

SQLSTATE usados: 23514 CHECK, 23505 UNIQUE, 23503 FK, 23502 NOT NULL, ALM12 histórico.
"""

import pytest

from almox.banco import Conexao, chamar_funcao

from .apoio import T0, espera_erro, horas, valor
from .cenario import Base, criar_consumo_com_saldo, criar_material, criar_unidades

pytestmark = pytest.mark.integracao

CHECK, UNIQUE, FK = "23514", "23505", "23503"


# ------------------------------------------------------------------ nomes (domain)
@pytest.mark.parametrize(
    "nome", ["", "   ", " Rádio", "Rádio ", "Rádio  Portátil", "x" * 121, "\tRádio"]
)
def test_domain_nome_recusa_espacos_e_vazio(bd: Conexao, nome: str) -> None:
    with espera_erro(bd, CHECK):
        bd.execute("INSERT INTO core.categoria (nome) VALUES (%s)", [nome])


def test_nome_unico_sem_diferenciar_maiusculas(bd: Conexao) -> None:
    bd.execute("INSERT INTO core.categoria (nome) VALUES ('Ferramentas Elétricas')")
    with espera_erro(bd, UNIQUE):
        bd.execute("INSERT INTO core.categoria (nome) VALUES ('FERRAMENTAS ELÉTRICAS')")


# ------------------------------------------------------------------ pessoa e usuário
@pytest.mark.parametrize("matricula", ["123456", "12345678", "12345a7", " 1234567"])
def test_matricula_com_formato_invalido(bd: Conexao, base: Base, matricula: str) -> None:
    with espera_erro(bd, CHECK):
        bd.execute(
            "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, "
            "posto_graduacao, nome_guerra) VALUES (%s, 'Fulano', %s, '2020-01-01', 'S1', 'Fulano')",
            [matricula, base.setor],
        )


def test_saida_antes_da_entrada(bd: Conexao, base: Base) -> None:
    with espera_erro(bd, CHECK):
        bd.execute(
            "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, data_saida, "
            "posto_graduacao, nome_guerra) "
            "VALUES ('1111111', 'Fulano', %s, '2020-01-01', '2019-12-31', 'S1', 'Fulano')",
            [base.setor],
        )


@pytest.mark.parametrize(
    ("login", "perfil"),
    [("Maiuscula", "ADMINISTRADOR"), ("ab", "ADMINISTRADOR"), ("ok.login", "CHEFE")],
)
def test_usuario_login_e_perfil_validos(bd: Conexao, base: Base, login: str, perfil: str) -> None:
    pessoa = valor(
        bd,
        "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, posto_graduacao, "
        "nome_guerra) VALUES ('2222222', 'Beltrano', %(s)s, '2020-01-01', 'S1', 'Beltrano') "
        "RETURNING id",
        {"s": base.setor},
    )
    with espera_erro(bd, CHECK):
        bd.execute(
            "INSERT INTO core.usuario (pessoa_id, login, perfil) VALUES (%s, %s, %s)",
            [pessoa, login, perfil],
        )


# ------------------------------------------------------------------ catálogo
@pytest.mark.parametrize(
    ("codigo", "controle", "unidade", "prazo", "custo"),
    [
        ("abc-0001", "SERIAL", "UN", 12, 1),  # código fora do padrão
        ("ABC-0001", "OUTRO", "UN", None, 1),  # controle inexistente
        ("ABC-0001", "SERIAL", "CX", None, 1),  # serial se conta em unidades
        ("ABC-0001", "CONSUMO", "CX", 12, 1),  # consumo não é cautelado
        ("ABC-0001", "SERIAL", "UN", 0, 1),  # prazo zero
        ("ABC-0001", "SERIAL", "UN", None, -1),  # custo negativo
        ("ABC-0001", "CONSUMO", "BALDE", None, 1),  # unidade de medida fora da lista
    ],
)
def test_catalogo_recusa_combinacoes_invalidas(
    bd: Conexao, base: Base, codigo: str, controle: str, unidade: str, prazo: int | None, custo: int
) -> None:
    with espera_erro(bd, CHECK):
        bd.execute(
            "INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, "
            "controle, prazo_devolucao_horas, custo_unitario) "
            "VALUES (%s, 'Item X', %s, %s, %s, %s, %s)",
            [codigo, base.subcategoria_serial, unidade, controle, prazo, custo],
        )


# ------------------------------------------------------------------ FKs compostas
def test_unidade_patrimonial_de_material_de_consumo_e_recusada(bd: Conexao, base: Base) -> None:
    consumo = criar_material(bd, base, "CONSUMO")
    with espera_erro(bd, FK):
        bd.execute(
            "INSERT INTO core.unidade_patrimonial (material_tipo_id, bmp, local_id, status) "
            "VALUES (%s, '1234567', %s, 'DISPONIVEL')",
            [consumo, base.local],
        )


def test_saldo_de_material_serial_e_recusado(bd: Conexao, base: Base) -> None:
    serial = criar_material(bd, base, "SERIAL", prazo_horas=12)
    with espera_erro(bd, FK):
        bd.execute(
            "INSERT INTO core.saldo_consumo (material_tipo_id, local_id, estoque_minimo, "
            "estoque_maximo) VALUES (%s, %s, 1, 10)",
            [serial, base.local],
        )


# ------------------------------------------------------------------ unidade patrimonial
@pytest.mark.parametrize(
    ("bmp", "status", "com_detentor"),
    [
        ("1234567", "CAUTELADA", False),  # cautelada sem detentor
        ("1234567", "DISPONIVEL", True),  # detentor sem cautela
        (None, "DISPONIVEL", False),  # sem BMP só aguardando tombamento
        ("1234567", "AGUARDANDO_TOMBAMENTO", False),  # com BMP não aguarda tombamento
        ("12345", "DISPONIVEL", False),  # BMP fora do formato
        ("1234567", "EMPRESTADA", False),  # status inexistente
    ],
)
def test_unidade_estado_incoerente_e_recusado(
    bd: Conexao, base: Base, bmp: str | None, status: str, com_detentor: bool
) -> None:
    serial = criar_material(bd, base, "SERIAL", prazo_horas=12)
    with espera_erro(bd, CHECK):
        bd.execute(
            "INSERT INTO core.unidade_patrimonial (material_tipo_id, bmp, local_id, status, "
            "detentor_id) VALUES (%s, %s, %s, %s, %s)",
            [serial, bmp, base.local, status, base.pessoa if com_detentor else None],
        )


def _inserir_unidade(bd: Conexao, base: Base, material: int, bmp: str, serie: str | None) -> None:
    bd.execute(
        "INSERT INTO core.unidade_patrimonial (material_tipo_id, bmp, numero_serie, local_id, "
        "status) VALUES (%s, %s, %s, %s, 'DISPONIVEL')",
        [material, bmp, serie, base.local],
    )


def test_bmp_duplicado_e_recusado(bd: Conexao, base: Base) -> None:
    serial = criar_material(bd, base, "SERIAL", prazo_horas=12)
    _inserir_unidade(bd, base, serial, "7654321", None)
    with espera_erro(bd, UNIQUE):
        _inserir_unidade(bd, base, serial, "7654321", None)


def test_numero_de_serie_repetido_no_mesmo_tipo_e_recusado(bd: Conexao, base: Base) -> None:
    serial = criar_material(bd, base, "SERIAL", prazo_horas=12)
    outro = criar_material(bd, base, "SERIAL", prazo_horas=12)
    _inserir_unidade(bd, base, serial, "7000001", "SN-001")
    _inserir_unidade(bd, base, outro, "7000002", "SN-001")  # outro tipo: pode
    _inserir_unidade(bd, base, serial, "7000003", None)  # sem série: pode repetir NULL
    _inserir_unidade(bd, base, serial, "7000004", None)
    with espera_erro(bd, UNIQUE):
        _inserir_unidade(bd, base, serial, "7000005", "SN-001")


# ------------------------------------------------------------------ saldo
def test_saldo_negativo_e_maximo_menor_que_minimo(bd: Conexao, base: Base) -> None:
    consumo = criar_consumo_com_saldo(bd, base, saldo=5)
    with espera_erro(bd, CHECK):
        bd.execute(
            "UPDATE core.saldo_consumo SET quantidade = -1 WHERE material_tipo_id = %s", [consumo]
        )
    with espera_erro(bd, CHECK):
        bd.execute(
            "UPDATE core.saldo_consumo SET estoque_minimo = 50, estoque_maximo = 10 "
            "WHERE material_tipo_id = %s",
            [consumo],
        )


# ------------------------------------------------------------------ histórico
def test_historico_nao_aceita_update_delete_truncate(bd: Conexao, base: Base) -> None:
    consumo = criar_consumo_com_saldo(bd, base, saldo=5)
    for comando in (
        "UPDATE core.movimentacao SET observacao = 'editado' WHERE material_tipo_id = %s",
        "DELETE FROM core.movimentacao WHERE material_tipo_id = %s",
    ):
        with espera_erro(bd, "ALM12"):
            bd.execute(comando, [consumo])
    with espera_erro(bd, "ALM12"):
        bd.execute("TRUNCATE core.movimentacao CASCADE")


def _mov_consumo(bd: Conexao, base: Base, material: int, **campos: object) -> None:
    valores: dict[str, object] = {
        "ocorrida_em": T0,
        "tipo": "RETIRADA",
        "material_tipo_id": material,
        "controle": "CONSUMO",
        "variacao": -1,
        "saldo_antes": 5,
        "saldo_depois": 4,
        "pessoa_id": base.pessoa,
        "executado_por": base.estoquista,
    }
    valores.update(campos)
    colunas = ", ".join(valores)
    marcadores = ", ".join(f"%({c})s" for c in valores)
    bd.execute(f"INSERT INTO core.movimentacao ({colunas}) VALUES ({marcadores})", valores)  # noqa: S608


def test_insert_direto_valido_no_historico_funciona(bd: Conexao, base: Base) -> None:
    """Controle positivo: garante que os testes negativos abaixo falham pela regra
    testada, e não por algum outro campo inválido no INSERT de base."""
    consumo = criar_consumo_com_saldo(bd, base, saldo=5)
    _mov_consumo(bd, base, consumo)


@pytest.mark.parametrize(
    "campos",
    [
        {"saldo_depois": 3},  # saldo depois não fecha com a variação
        {"variacao": 0, "saldo_depois": 5},  # variação zero
        {"saldo_antes": 0, "saldo_depois": -1},  # saldo negativo
        {"tipo": "ENTRADA"},  # entrada com variação negativa
        {"tipo": "MUDANCA_STATUS"},  # tipo que não existe para consumo
        {"pessoa_id": None},  # retirada sem pessoa
        {"status_novo": "DISPONIVEL"},  # campo de serial num consumo
        {"estado_devolucao": "BOM"},  # estado só em devolução
        {"tipo": "ESTORNO"},  # estorno sem apontar a original
        {"ocorrida_em": horas(24 * 365 * 5)},  # fato no futuro
        {"observacao": "x" * 501},  # texto longo demais
    ],
)
def test_historico_recusa_movimentacao_incoerente(
    bd: Conexao, base: Base, campos: dict[str, object]
) -> None:
    consumo = criar_consumo_com_saldo(bd, base, saldo=5)
    with espera_erro(bd, CHECK):
        _mov_consumo(bd, base, consumo, **campos)


def test_movimentacao_de_unidade_com_material_trocado_e_recusada(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    outro = criar_material(bd, base, "SERIAL", prazo_horas=12)
    (unidade,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, FK):
        bd.execute(
            "INSERT INTO core.movimentacao (ocorrida_em, tipo, material_tipo_id, controle, "
            "unidade_id, status_anterior, status_novo, executado_por) "
            "VALUES (%s, 'MUDANCA_STATUS', %s, 'SERIAL', %s, 'DISPONIVEL', "
            "'EM_MANUTENCAO', %s)",
            [T0, outro, unidade, base.estoquista],
        )


def test_funcao_rejeita_parametro_nao_numerico_sem_executar(bd: Conexao, base: Base) -> None:
    """Parâmetros vão separados do SQL: texto malicioso num id vira erro de tipo."""
    with espera_erro(bd, "22P02"):  # invalid_text_representation
        chamar_funcao(
            bd,
            "registrar_retirada_unidade",
            p_unidade_id="1; DROP TABLE core.movimentacao",
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
        )
