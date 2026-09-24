"""Rastreabilidade, estorno e auditoria do estado contra o histórico."""

from itertools import pairwise

import pytest

from almox.banco import Conexao, chamar_funcao

from .apoio import espera_erro, horas, valor
from .cenario import Base, criar_consumo_com_saldo, criar_material, criar_unidades
from .operacoes import alterar, devolver, estado, retirar

pytestmark = pytest.mark.integracao


def estornar(
    bd: Conexao,
    base: Base,
    mov: object,
    quando: float = 50,
    usuario: int | None = None,
    justificativa: str | None = "Lançamento na pessoa errada",
) -> object:
    return chamar_funcao(
        bd,
        "estornar_movimentacao",
        p_movimentacao_id=mov,
        p_executado_por=usuario or base.admin,
        p_justificativa=justificativa,
        p_ocorrida_em=horas(quando),
    )


def divergencias(bd: Conexao) -> list[tuple[object, ...]]:
    return [tuple(linha) for linha in bd.execute("SELECT * FROM core.vw_divergencia_estado")]


@pytest.fixture
def radio(bd: Conexao, base: Base) -> int:
    return criar_material(bd, base, "SERIAL", prazo_horas=12)


# ------------------------------------------------------------------ rastreabilidade
def test_historico_reconstroi_entrada_retirada_devolucao_nova_retirada(
    bd: Conexao, base: Base, radio: int
) -> None:
    (unidade,) = criar_unidades(bd, base, radio, quando=horas(0))
    retirar(bd, base, unidade, quando=1, pessoa=base.pessoa)
    devolver(bd, base, unidade, quando=12, pessoa=base.pessoa)
    retirar(bd, base, unidade, quando=24, pessoa=base.pessoa2)

    linhas = bd.execute(
        "SELECT tipo, ocorrida_em, status_anterior, status_novo, pessoa_id, executado_por "
        "FROM core.movimentacao WHERE unidade_id = %s ORDER BY ocorrida_em, id",
        [unidade],
    ).fetchall()
    assert linhas == [
        ("ENTRADA", horas(0), None, "DISPONIVEL", None, base.estoquista),
        ("RETIRADA", horas(1), "DISPONIVEL", "CAUTELADA", base.pessoa, base.equipamentista),
        ("DEVOLUCAO", horas(12), "CAUTELADA", "DISPONIVEL", base.pessoa, base.equipamentista),
        ("RETIRADA", horas(24), "DISPONIVEL", "CAUTELADA", base.pessoa2, base.equipamentista),
    ]
    # Cada movimentação começa onde a anterior terminou.
    for anterior, atual in pairwise(linhas):
        assert atual[2] == anterior[3]
    assert estado(bd, unidade) == ("CAUTELADA", base.pessoa2)
    assert divergencias(bd) == []


def test_saldo_encadeado_no_historico_de_consumo(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=50)
    for i, qtd in enumerate([5, 10, 3]):
        chamar_funcao(
            bd,
            "registrar_retirada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=qtd,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(1 + i),
        )
    linhas = bd.execute(
        "SELECT saldo_antes, variacao, saldo_depois FROM core.movimentacao "
        "WHERE material_tipo_id = %s ORDER BY ocorrida_em, id",
        [papel],
    ).fetchall()
    assert linhas == [(0, 50, 50), (50, -5, 45), (45, -10, 35), (35, -3, 32)]
    assert divergencias(bd) == []


# ------------------------------------------------------------------ estorno de consumo
def test_estorno_de_retirada_devolve_o_saldo(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=50)
    mov = chamar_funcao(
        bd,
        "registrar_retirada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=8,
        p_pessoa_id=base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(1),
    )
    estorno = estornar(bd, base, mov)
    linha = bd.execute(
        "SELECT tipo, variacao, saldo_antes, saldo_depois, estorno_de_id FROM core.movimentacao "
        "WHERE id = %s",
        [estorno],
    ).fetchone()
    assert linha == ("ESTORNO", 8, 42, 50, mov)
    # A original continua no histórico, intacta.
    assert valor(bd, "SELECT variacao FROM core.movimentacao WHERE id = %(i)s", {"i": mov}) == -8
    assert divergencias(bd) == []


def test_estorno_de_entrada_ja_consumida_deixaria_saldo_negativo(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=0)
    entrada = chamar_funcao(
        bd,
        "registrar_entrada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=10,
        p_executado_por=base.estoquista,
        p_ocorrida_em=horas(1),
    )
    chamar_funcao(
        bd,
        "registrar_retirada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=7,
        p_pessoa_id=base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(2),
    )
    with espera_erro(bd, "ALM01"):
        estornar(bd, base, entrada)


def test_nao_se_estorna_duas_vezes_nem_um_estorno(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=50)
    mov = chamar_funcao(
        bd,
        "registrar_retirada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=1,
        p_pessoa_id=base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(1),
    )
    estorno = estornar(bd, base, mov)
    with espera_erro(bd, "ALM07"):
        estornar(bd, base, mov, quando=51)
    with espera_erro(bd, "ALM07"):
        estornar(bd, base, estorno, quando=52)


@pytest.mark.parametrize(
    ("usuario", "justificativa", "codigo"),
    [("estoquista", "ok", "ALM05"), ("equipamentista", "ok", "ALM05"), ("admin", "  ", "ALM10")],
)
def test_estorno_so_pelo_administrador_com_justificativa(
    bd: Conexao, base: Base, usuario: str, justificativa: str, codigo: str
) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=5)
    mov = valor(
        bd, "SELECT max(id) FROM core.movimentacao WHERE material_tipo_id = %(m)s", {"m": papel}
    )
    with espera_erro(bd, codigo):
        estornar(bd, base, mov, usuario=getattr(base, usuario), justificativa=justificativa)


def test_estorno_de_movimentacao_inexistente(bd: Conexao, base: Base) -> None:
    with espera_erro(bd, "ALM09"):
        estornar(bd, base, 9_000_000_000)


# ------------------------------------------------------------------ estorno de serial
def test_estorno_de_retirada_libera_a_unidade(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    mov = retirar(bd, base, unidade)
    estornar(bd, base, mov)
    assert estado(bd, unidade) == ("DISPONIVEL", None)
    assert divergencias(bd) == []


def test_estorno_de_devolucao_volta_a_cautela_para_o_detentor(
    bd: Conexao, base: Base, radio: int
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade, pessoa=base.pessoa2)
    mov = devolver(bd, base, unidade, pessoa=base.pessoa2)
    estornar(bd, base, mov)
    assert estado(bd, unidade) == ("CAUTELADA", base.pessoa2)
    assert divergencias(bd) == []


def test_estorno_de_nao_localizada_devolve_a_cautela(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    mov = alterar(bd, base, unidade, "NAO_LOCALIZADA", quando=20)
    estornar(bd, base, mov)
    assert estado(bd, unidade) == ("CAUTELADA", base.pessoa)
    assert divergencias(bd) == []


def test_estorno_de_tombamento_remove_o_bmp(bd: Conexao, base: Base, radio: int) -> None:
    unidade = chamar_funcao(
        bd,
        "registrar_entrada_unidade",
        p_material_tipo_id=radio,
        p_local_id=base.local,
        p_executado_por=base.estoquista,
        p_ocorrida_em=horas(0),
    )
    mov = alterar(bd, base, unidade, "DISPONIVEL", bmp="6666666")
    estornar(bd, base, mov)
    linha = bd.execute(
        "SELECT status, bmp FROM core.unidade_patrimonial WHERE id = %s", [unidade]
    ).fetchone()
    assert linha == ("AGUARDANDO_TOMBAMENTO", None)
    assert divergencias(bd) == []


def test_so_a_ultima_movimentacao_da_unidade_e_estornavel(
    bd: Conexao, base: Base, radio: int
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirada = retirar(bd, base, unidade)
    devolver(bd, base, unidade)
    with espera_erro(bd, "ALM07"):
        estornar(bd, base, retirada)


def test_entrada_de_unidade_nao_se_estorna(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    entrada = valor(bd, "SELECT id FROM core.movimentacao WHERE unidade_id = %(u)s", {"u": unidade})
    with espera_erro(bd, "ALM07"):
        estornar(bd, base, entrada)


# ------------------------------------------------------------------ auditoria do estado
def test_view_detecta_estado_alterado_por_fora_das_funcoes(
    bd: Conexao, base: Base, radio: int
) -> None:
    """Simula um cliente com defeito que altera o estado direto na tabela."""
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    (unidade,) = criar_unidades(bd, base, radio)
    assert divergencias(bd) == []

    bd.execute(
        "UPDATE core.saldo_consumo SET quantidade = 999 WHERE material_tipo_id = %s", [papel]
    )
    bd.execute(
        "UPDATE core.unidade_patrimonial SET status = 'EM_MANUTENCAO' WHERE id = %s", [unidade]
    )
    assert sorted(divergencias(bd)) == sorted(
        [
            ("SALDO", papel, "quantidade=999", "quantidade=10"),
            ("UNIDADE", unidade, "status=EM_MANUTENCAO detentor=", "status=DISPONIVEL detentor="),
        ]
    )
