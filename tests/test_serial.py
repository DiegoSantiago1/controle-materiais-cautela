"""Regras de material patrimonial: incorporação, cautela, devolução e situação."""

from datetime import timedelta

import pytest

from almox.banco import Conexao, chamar_funcao

from .apoio import T0, espera_erro, horas, valor
from .cenario import Base, criar_material, criar_unidades
from .operacoes import alterar, devolver, estado, retirar

pytestmark = pytest.mark.integracao


@pytest.fixture
def radio(bd: Conexao, base: Base) -> int:
    """Tipo de material cautelável com prazo de um turno (12 h)."""
    return criar_material(bd, base, "SERIAL", prazo_horas=12)


# ------------------------------------------------------------------ incorporação
def test_entrada_cria_unidade_disponivel_e_registra_historico(
    bd: Conexao, base: Base, radio: int
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    assert estado(bd, unidade) == ("DISPONIVEL", None)
    linha = bd.execute(
        "SELECT tipo, status_anterior, status_novo, executado_por FROM core.movimentacao "
        "WHERE unidade_id = %s",
        [unidade],
    ).fetchone()
    assert linha == ("ENTRADA", None, "DISPONIVEL", base.estoquista)


def test_entrada_sem_bmp_aguarda_tombamento(bd: Conexao, base: Base, radio: int) -> None:
    unidade = chamar_funcao(
        bd,
        "registrar_entrada_unidade",
        p_material_tipo_id=radio,
        p_local_id=base.local,
        p_executado_por=base.estoquista,
        p_bmp="   ",  # em branco conta como ausente
        p_ocorrida_em=T0,
    )
    assert estado(bd, unidade) == ("AGUARDANDO_TOMBAMENTO", None)


def test_entrada_de_material_de_consumo_pela_funcao_serial(bd: Conexao, base: Base) -> None:
    papel = criar_material(bd, base, "CONSUMO")
    with espera_erro(bd, "ALM02"):
        chamar_funcao(
            bd,
            "registrar_entrada_unidade",
            p_material_tipo_id=papel,
            p_local_id=base.local,
            p_executado_por=base.estoquista,
            p_bmp="1234567",
            p_ocorrida_em=T0,
        )


def test_equipamentista_nao_incorpora_unidade(bd: Conexao, base: Base, radio: int) -> None:
    with espera_erro(bd, "ALM05"):
        chamar_funcao(
            bd,
            "registrar_entrada_unidade",
            p_material_tipo_id=radio,
            p_local_id=base.local,
            p_executado_por=base.equipamentista,
            p_bmp="1234567",
            p_ocorrida_em=T0,
        )


# ------------------------------------------------------------------ cautela
def test_retirada_cautela_a_unidade_com_prazo_padrao(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    mov = retirar(bd, base, unidade, quando=1)
    assert estado(bd, unidade) == ("CAUTELADA", base.pessoa)
    prazo = valor(bd, "SELECT prazo_devolucao FROM core.movimentacao WHERE id = %(i)s", {"i": mov})
    assert prazo == horas(1) + timedelta(hours=12)


def test_prazo_informado_antes_da_retirada_e_recusado(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, "ALM10"):
        retirar(bd, base, unidade, quando=5, p_prazo_devolucao=horas(4))


def test_unidade_ja_cautelada_nao_sai_de_novo(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    with espera_erro(bd, "ALM02"):
        retirar(bd, base, unidade, quando=1.5, pessoa=base.pessoa2)
    assert estado(bd, unidade) == ("CAUTELADA", base.pessoa)


def test_material_nao_cautelavel(bd: Conexao, base: Base) -> None:
    armario = criar_material(bd, base, "SERIAL", prazo_horas=None)
    (unidade,) = criar_unidades(bd, base, armario)
    with espera_erro(bd, "ALM02"):
        retirar(bd, base, unidade)


def test_unidade_inexistente(bd: Conexao, base: Base) -> None:
    with espera_erro(bd, "ALM09"):
        retirar(bd, base, 2_147_483_647)


def test_pessoa_transferida_nao_recebe_cautela(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, "ALM03"):
        retirar(bd, base, unidade, pessoa=base.pessoa_transferida)
    assert estado(bd, unidade) == ("DISPONIVEL", None)


def test_consulta_nao_registra_cautela(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, "ALM05"):
        chamar_funcao(
            bd,
            "registrar_retirada_unidade",
            p_unidade_id=unidade,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.consulta,
            p_ocorrida_em=horas(1),
        )


def test_retirada_antes_da_ultima_movimentacao(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio, quando=horas(10))
    with espera_erro(bd, "ALM08"):
        retirar(bd, base, unidade, quando=9)


# ------------------------------------------------------------------ devolução
def test_pessoa_com_cinco_devolve_duas_fica_com_tres(bd: Conexao, base: Base, radio: int) -> None:
    unidades = criar_unidades(bd, base, radio, quantidade=5)
    for u in unidades:
        retirar(bd, base, u)

    def com_a_pessoa() -> object:
        return valor(
            bd,
            "SELECT count(*) FROM core.unidade_patrimonial WHERE detentor_id = %(p)s "
            "AND material_tipo_id = %(m)s",
            {"p": base.pessoa, "m": radio},
        )

    def disponiveis() -> object:
        return valor(
            bd,
            "SELECT count(*) FROM core.unidade_patrimonial WHERE status = 'DISPONIVEL' "
            "AND material_tipo_id = %(m)s",
            {"m": radio},
        )

    assert (com_a_pessoa(), disponiveis()) == (5, 0)
    for u in unidades[:2]:
        devolver(bd, base, u)
    assert (com_a_pessoa(), disponiveis()) == (3, 2)


@pytest.mark.parametrize(
    ("estado_material", "status_esperado"),
    [("BOM", "DISPONIVEL"), ("AVARIADO", "EM_MANUTENCAO"), ("INSERVIVEL", "BAIXA_PENDENTE")],
)
def test_estado_na_devolucao_define_a_situacao(
    bd: Conexao, base: Base, radio: int, estado_material: str, status_esperado: str
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    devolver(bd, base, unidade, estado_material=estado_material, observacao="Antena quebrada")
    assert estado(bd, unidade) == (status_esperado, None)


def test_devolucao_com_avaria_exige_observacao(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    with espera_erro(bd, "ALM10"):
        devolver(bd, base, unidade, estado_material="AVARIADO", observacao=" ")


def test_estado_de_devolucao_invalido(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    with espera_erro(bd, "ALM10"):
        devolver(bd, base, unidade, estado_material="OTIMO")


def test_so_o_detentor_devolve(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    with espera_erro(bd, "ALM04"):
        devolver(bd, base, unidade, pessoa=base.pessoa2)
    assert estado(bd, unidade) == ("CAUTELADA", base.pessoa)


def test_devolver_unidade_que_nao_esta_cautelada(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, "ALM02"):
        devolver(bd, base, unidade)


def test_devolucao_antes_da_retirada(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade, quando=5)
    with espera_erro(bd, "ALM08"):
        devolver(bd, base, unidade, quando=4)


# ------------------------------------------------------------------ situação
@pytest.mark.parametrize(
    ("caminho", "final"),
    [
        (["EM_MANUTENCAO", "DISPONIVEL"], "DISPONIVEL"),
        (["NAO_LOCALIZADA", "DISPONIVEL"], "DISPONIVEL"),
        (["BAIXA_PENDENTE", "BAIXADA"], "BAIXADA"),
        (["EM_MANUTENCAO", "BAIXA_PENDENTE", "DISPONIVEL"], "DISPONIVEL"),
    ],
)
def test_transicoes_permitidas(
    bd: Conexao, base: Base, radio: int, caminho: list[str], final: str
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    for i, status in enumerate(caminho):
        alterar(bd, base, unidade, status, quando=1 + i)
    assert estado(bd, unidade) == (final, None)


@pytest.mark.parametrize(
    ("preparo", "novo"),
    [
        ([], "CAUTELADA"),  # cautela só pela retirada
        ([], "BAIXADA"),  # baixa só depois de BAIXA_PENDENTE
        ([], "DISPONIVEL"),  # já está disponível
        ([], "AGUARDANDO_TOMBAMENTO"),
        ([], "INEXISTENTE"),
        ([], None),
        (["BAIXA_PENDENTE", "BAIXADA"], "DISPONIVEL"),  # baixada é definitiva
    ],
)
def test_transicoes_proibidas(
    bd: Conexao, base: Base, radio: int, preparo: list[str], novo: str | None
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    for i, status in enumerate(preparo):
        alterar(bd, base, unidade, status, quando=1 + i)
    with espera_erro(bd, "ALM06"):
        alterar(bd, base, unidade, novo, quando=10)


def test_unidade_cautelada_nao_localizada_guarda_com_quem_estava(
    bd: Conexao, base: Base, radio: int
) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade)
    mov = alterar(bd, base, unidade, "NAO_LOCALIZADA", quando=500)
    assert estado(bd, unidade) == ("NAO_LOCALIZADA", None)
    assert valor(bd, "SELECT pessoa_id FROM core.movimentacao WHERE id = %(i)s", {"i": mov}) == (
        base.pessoa
    )


def test_mudanca_de_situacao_exige_justificativa(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, "ALM10"):
        alterar(bd, base, unidade, "EM_MANUTENCAO", justificativa="")


def test_baixa_definitiva_so_pelo_administrador(bd: Conexao, base: Base, radio: int) -> None:
    (unidade,) = criar_unidades(bd, base, radio)
    alterar(bd, base, unidade, "BAIXA_PENDENTE", usuario=base.estoquista)
    with espera_erro(bd, "ALM05"):
        alterar(bd, base, unidade, "BAIXADA", quando=4, usuario=base.estoquista)


def test_tombamento_exige_bmp_e_so_nele_se_informa_bmp(bd: Conexao, base: Base, radio: int) -> None:
    sem_bmp = chamar_funcao(
        bd,
        "registrar_entrada_unidade",
        p_material_tipo_id=radio,
        p_local_id=base.local,
        p_executado_por=base.estoquista,
        p_ocorrida_em=T0,
    )
    with espera_erro(bd, "ALM10"):
        alterar(bd, base, sem_bmp, "DISPONIVEL")  # sem BMP
    alterar(bd, base, sem_bmp, "DISPONIVEL", bmp="7777777")
    assert valor(
        bd, "SELECT bmp FROM core.unidade_patrimonial WHERE id = %(u)s", {"u": sem_bmp}
    ) == ("7777777")

    (com_bmp,) = criar_unidades(bd, base, radio)
    with espera_erro(bd, "ALM10"):
        alterar(bd, base, com_bmp, "EM_MANUTENCAO", bmp="7777778")  # BMP fora do tombamento
