"""Regras de estoque de consumo: entrada, retirada, ajuste de inventário."""

import pytest

from almox.banco import Conexao, chamar_funcao

from .apoio import espera_erro, horas, valor
from .cenario import Base, criar_consumo_com_saldo, criar_material

pytestmark = pytest.mark.integracao


def saldo(bd: Conexao, material: int) -> object:
    return valor(
        bd,
        "SELECT quantidade FROM core.saldo_consumo WHERE material_tipo_id = %(m)s",
        {"m": material},
    )


def movimentos(bd: Conexao, material: int) -> int:
    n = valor(
        bd, "SELECT count(*) FROM core.movimentacao WHERE material_tipo_id = %(m)s", {"m": material}
    )
    assert isinstance(n, int)
    return n


def entrada(bd: Conexao, base: Base, material: int, qtd: object, quando: float = 1) -> object:
    return chamar_funcao(
        bd,
        "registrar_entrada_consumo",
        p_material_tipo_id=material,
        p_quantidade=qtd,
        p_executado_por=base.estoquista,
        p_ocorrida_em=horas(quando),
    )


def retirada(
    bd: Conexao,
    base: Base,
    material: int,
    qtd: object,
    quando: float = 1,
    pessoa: int | None = None,
    usuario: int | None = None,
) -> object:
    return chamar_funcao(
        bd,
        "registrar_retirada_consumo",
        p_material_tipo_id=material,
        p_quantidade=qtd,
        p_pessoa_id=pessoa or base.pessoa,
        p_executado_por=usuario or base.equipamentista,
        p_ocorrida_em=horas(quando),
    )


# ------------------------------------------------------------------ caminho feliz
def test_entrada_soma_ao_saldo_e_registra_antes_e_depois(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=100)
    mov = entrada(bd, base, papel, 20)
    assert saldo(bd, papel) == 120
    linha = bd.execute(
        "SELECT tipo, variacao, saldo_antes, saldo_depois, executado_por "
        "FROM core.movimentacao WHERE id = %s",
        [mov],
    ).fetchone()
    assert linha == ("ENTRADA", 20, 100, 120, base.estoquista)


def test_retirada_subtrai_do_saldo(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=100)
    mov = retirada(bd, base, papel, 30)
    assert saldo(bd, papel) == 70
    linha = bd.execute(
        "SELECT tipo, variacao, saldo_antes, saldo_depois, pessoa_id FROM core.movimentacao "
        "WHERE id = %s",
        [mov],
    ).fetchone()
    assert linha == ("RETIRADA", -30, 100, 70, base.pessoa)


def test_retirada_de_todo_o_saldo_e_permitida(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    retirada(bd, base, papel, 10)
    assert saldo(bd, papel) == 0


# ------------------------------------------------------------------ estoque insuficiente
def test_retirada_acima_do_saldo_e_rejeitada_sem_efeito(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    antes = movimentos(bd, papel)
    with espera_erro(bd, "ALM01"):
        retirada(bd, base, papel, 20)
    assert saldo(bd, papel) == 10
    assert movimentos(bd, papel) == antes


def test_retirada_de_material_com_saldo_zero(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=0)
    with espera_erro(bd, "ALM01"):
        retirada(bd, base, papel, 1)


# ------------------------------------------------------------------ entradas inválidas
@pytest.mark.parametrize("qtd", [0, -5, None])
@pytest.mark.parametrize("operacao", ["entrada", "retirada"])
def test_quantidade_invalida(bd: Conexao, base: Base, qtd: int | None, operacao: str) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM10"):
        if operacao == "entrada":
            entrada(bd, base, papel, qtd)
        else:
            retirada(bd, base, papel, qtd)
    assert saldo(bd, papel) == 10


def test_quantidade_maior_que_integer_e_recusada(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "22003"):  # numeric_value_out_of_range
        entrada(bd, base, papel, "3000000000")


def test_estouro_do_saldo_por_soma_e_recusado(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "22003"):
        entrada(bd, base, papel, 2_147_483_647)


def test_material_inexistente(bd: Conexao, base: Base) -> None:
    with espera_erro(bd, "ALM09"):
        entrada(bd, base, 2_147_483_647, 5)


def test_material_serial_na_funcao_de_consumo(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    with espera_erro(bd, "ALM02"):
        entrada(bd, base, radio, 5)


# ------------------------------------------------------------------ pessoa
def test_pessoa_inexistente(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM09"):
        retirada(bd, base, papel, 1, pessoa=2_147_483_647)


def test_pessoa_transferida_nao_retira(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM03"):
        retirada(bd, base, papel, 1, pessoa=base.pessoa_transferida)


def test_pessoa_que_ainda_nao_chegou_nao_retira(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM03"):
        retirada(bd, base, papel, 1, pessoa=base.pessoa_nova)


# ------------------------------------------------------------------ permissões
@pytest.mark.parametrize("perfil", ["consulta", "usuario_inativo"])
def test_sem_permissao_para_retirar(bd: Conexao, base: Base, perfil: str) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM05"):
        retirada(bd, base, papel, 1, usuario=getattr(base, perfil))


def test_equipamentista_nao_registra_entrada(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM05"):
        chamar_funcao(
            bd,
            "registrar_entrada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=5,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(1),
        )


def test_usuario_inexistente(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM05"):
        retirada(bd, base, papel, 1, usuario=2_147_483_647)


# ------------------------------------------------------------------ tempo
def test_movimentacao_anterior_a_ultima_e_recusada(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    retirada(bd, base, papel, 1, quando=5)
    with espera_erro(bd, "ALM08"):
        retirada(bd, base, papel, 1, quando=4)


def test_data_nula_e_recusada(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "ALM08"):
        chamar_funcao(
            bd,
            "registrar_retirada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=1,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=None,
        )


def test_movimentacao_no_futuro_e_recusada(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    with espera_erro(bd, "23514"):  # ck_mov_nao_futura
        retirada(bd, base, papel, 1, quando=24 * 365 * 5)


# ------------------------------------------------------------------ ajuste de inventário
def test_ajuste_lanca_a_diferenca_da_contagem(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=100)
    mov = chamar_funcao(
        bd,
        "registrar_ajuste_consumo",
        p_material_tipo_id=papel,
        p_quantidade_contada=95,
        p_executado_por=base.estoquista,
        p_justificativa="Inventário mensal: 5 resmas danificadas por umidade",
        p_ocorrida_em=horas(2),
    )
    assert saldo(bd, papel) == 95
    linha = bd.execute(
        "SELECT tipo, variacao, saldo_antes, saldo_depois FROM core.movimentacao WHERE id = %s",
        [mov],
    ).fetchone()
    assert linha == ("AJUSTE", -5, 100, 95)


def test_ajuste_sem_diferenca_nao_lanca_nada(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=100)
    antes = movimentos(bd, papel)
    mov = chamar_funcao(
        bd,
        "registrar_ajuste_consumo",
        p_material_tipo_id=papel,
        p_quantidade_contada=100,
        p_executado_por=base.estoquista,
        p_justificativa="Contagem confere",
        p_ocorrida_em=horas(2),
    )
    assert mov is None
    assert movimentos(bd, papel) == antes


@pytest.mark.parametrize(
    ("contada", "justificativa"), [(-1, "x"), (None, "x"), (90, "  "), (90, None)]
)
def test_ajuste_invalido(
    bd: Conexao, base: Base, contada: int | None, justificativa: str | None
) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=100)
    with espera_erro(bd, "ALM10"):
        chamar_funcao(
            bd,
            "registrar_ajuste_consumo",
            p_material_tipo_id=papel,
            p_quantidade_contada=contada,
            p_executado_por=base.estoquista,
            p_justificativa=justificativa,
            p_ocorrida_em=horas(2),
        )


def test_texto_malicioso_e_gravado_literalmente(bd: Conexao, base: Base) -> None:
    """Parâmetros nunca viram SQL; HTML é guardado como texto (escapar é papel de quem
    exibe, na interface)."""
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    texto = "'); DROP TABLE core.movimentacao; -- <script>alert(1)</script>"
    mov = chamar_funcao(
        bd,
        "registrar_retirada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=1,
        p_pessoa_id=base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(1),
        p_finalidade=texto,
    )
    assert (
        valor(bd, "SELECT finalidade FROM core.movimentacao WHERE id = %(i)s", {"i": mov}) == texto
    )
    assert valor(bd, "SELECT to_regclass('core.movimentacao') IS NOT NULL") is True
