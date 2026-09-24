"""A2 — cautelas reconstruídas do histórico e análise de atraso."""

import json

import numpy as np
import pandas as pd
import pytest

from almox.analise import cautela as a2
from almox.banco import Conexao, chamar_funcao, engine
from almox.config import ConfigBanco

from .apoio import CargaPadrao, horas
from .cenario import Base, criar_material, criar_unidades
from .operacoes import alterar, devolver, retirar


# ================================================================== Wilson (sem banco)
def test_wilson_confere_com_a_formula_em_valores_conhecidos() -> None:
    inferior, superior = a2.wilson(np.array([5, 0, 10]), np.array([10, 10, 10]))
    # 5/10: intervalo simétrico em torno de 0,5 (valores de referência da fórmula).
    assert inferior[0] == pytest.approx(0.2366, abs=1e-4)
    assert superior[0] == pytest.approx(0.7634, abs=1e-4)
    # 0/10 e 10/10: o intervalo não colapsa em 0 ou 1 (ao contrário do intervalo normal).
    assert inferior[1] == 0 and superior[1] == pytest.approx(0.2775, abs=1e-4)
    assert superior[2] == 1 and inferior[2] == pytest.approx(0.7225, abs=1e-4)


def test_wilson_fica_mais_estreito_com_mais_dados() -> None:
    inferior, superior = a2.wilson(np.array([1, 100]), np.array([2, 200]))
    assert (superior - inferior)[0] > (superior - inferior)[1]


def test_wilson_sem_observacoes_e_indefinido() -> None:
    inferior, superior = a2.wilson(np.array([0]), np.array([0]))
    assert np.isnan(inferior[0]) and np.isnan(superior[0])


def _cautelas(linhas: list[tuple[str, str, str, bool]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "matricula": m,
                "pessoa": m,
                "setor": s,
                "subcategoria": sub,
                "atrasada": a,
                "situacao": "DEVOLVIDA",
            }
            for m, s, sub, a in linhas
        ]
    )


def test_material_que_atrasa_para_todos_nao_acusa_a_pessoa() -> None:
    """Quem só retira o material problemático atrasa tanto quanto o esperado dele."""
    linhas = [("A", "MANUT", "Eletrica", i % 2 == 0) for i in range(40)]  # 50% em elétrica
    linhas += [("B", "MANUT", "Eletrica", i % 2 == 0) for i in range(40)]
    linhas += [("C", "SEG", "Radio", i % 10 == 0) for i in range(100)]  # 10% em rádio
    linhas += [("D", "SEG", "Radio", i % 2 == 0) for i in range(40)]  # 50% em rádio!
    resultado = a2.atraso_por_pessoa(_cautelas(linhas)).set_index("matricula")
    assert resultado.loc["D", "apontada"]
    assert not resultado.loc[["A", "B", "C"], "apontada"].any()


def test_poucas_cautelas_nunca_bastam_para_apontar() -> None:
    linhas = [("X", "ADM", "Radio", True)] * 5 + [("Y", "ADM", "Radio", False)] * 100
    resultado = a2.atraso_por_pessoa(_cautelas(linhas)).set_index("matricula")
    assert resultado.loc["X", "observada"] == 1.0
    assert not resultado.loc["X", "apontada"]  # 5 < MIN_CAUTELAS


# ================================================================== reconstrução (SQL)
def _cautelas_da_unidade(bd: Conexao, unidade: int) -> list[tuple[object, ...]]:
    return [
        tuple(linha)
        for linha in bd.execute(
            "SELECT pessoa_id, situacao, retirada_em, devolvida_em, atrasada "
            "FROM analise.vw_cautela WHERE unidade_id = %s ORDER BY retirada_em",
            [unidade],
        )
    ]


@pytest.mark.integracao
def test_estornos_nao_quebram_o_pareamento(bd: Conexao, base: Base) -> None:
    """Retirada estornada some; devolução estornada reabre a cautela até a nova."""
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    (unidade,) = criar_unidades(bd, base, radio)
    errada = retirar(bd, base, unidade, quando=1, pessoa=base.pessoa2)
    chamar_funcao(
        bd,
        "estornar_movimentacao",
        p_movimentacao_id=errada,
        p_executado_por=base.admin,
        p_justificativa="pessoa errada",
        p_ocorrida_em=horas(1.05),
    )
    retirar(bd, base, unidade, quando=1.1, pessoa=base.pessoa)
    devolucao = devolver(bd, base, unidade, quando=5, pessoa=base.pessoa)
    chamar_funcao(
        bd,
        "estornar_movimentacao",
        p_movimentacao_id=devolucao,
        p_executado_por=base.admin,
        p_justificativa="devolução lançada antes",
        p_ocorrida_em=horas(5.1),
    )
    devolver(bd, base, unidade, quando=20, pessoa=base.pessoa)  # depois do prazo de 12 h

    assert _cautelas_da_unidade(bd, unidade) == [
        (base.pessoa, "DEVOLVIDA", horas(1.1), horas(20), True),
    ]


@pytest.mark.integracao
def test_cautela_aberta_e_nao_localizada(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    aberta, perdida = criar_unidades(bd, base, radio, quantidade=2)
    retirar(bd, base, aberta, quando=1)
    retirar(bd, base, perdida, quando=1, pessoa=base.pessoa2)
    alterar(bd, base, perdida, "NAO_LOCALIZADA", quando=300)
    assert [s for _, s, *_ in _cautelas_da_unidade(bd, aberta)] == ["EM_ABERTO"]
    assert [s for _, s, *_ in _cautelas_da_unidade(bd, perdida)] == ["NAO_LOCALIZADA"]


# ================================================================== conjunto carregado
@pytest.mark.integracao
@pytest.mark.lento
def test_analise_acha_os_reincidentes_sem_acusar_pontuais(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    e = engine(banco_teste)
    try:
        cautelas = a2.ler_cautelas(e)
    finally:
        e.dispose()
    verdade = json.loads((carga_padrao.pasta / "gabarito_padroes.json").read_text(encoding="utf-8"))
    perfil = verdade["perfil_pontualidade"]
    cautelas = cautelas[cautelas["matricula"].isin(perfil)]  # só as pessoas do conjunto
    pessoas = a2.atraso_por_pessoa(cautelas)
    apontadas = pessoas[pessoas["apontada"]]
    reincidentes = {m for m, p in perfil.items() if p == "reincidente"}
    assert reincidentes <= set(apontadas["matricula"])  # acha todos
    assert "pontual" not in set(apontadas["matricula"].map(perfil))  # não acusa pontual

    turno = a2.resumo_turno(cautelas)
    assert 0.85 <= turno["mesmo_dia"] <= 0.93
