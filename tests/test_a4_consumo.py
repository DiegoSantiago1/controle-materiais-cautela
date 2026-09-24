"""A4 — consumo, rupturas (gaps and islands), prazo de entrega e ponto de reposição."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from almox.analise import consumo as a4
from almox.banco import Conexao, chamar_funcao, engine
from almox.config import ConfigBanco

from .apoio import CargaPadrao, horas
from .cenario import Base, criar_consumo_com_saldo


# ================================================================== fórmulas (sem banco)
def test_ponto_de_reposicao_em_valores_conhecidos() -> None:
    # d=2/dia, var_d=4, prazo=10 dias sem variação: 20 + 1,65·√(10·4) = 30,435
    assert a4.ponto_de_reposicao(
        np.array([2.0]), np.array([4.0]), np.array([10.0]), np.array([0.0])
    )[0] == pytest.approx(30.435, abs=1e-3)
    # Sem nenhuma variação, é só a demanda durante o prazo.
    assert a4.ponto_de_reposicao(
        np.array([3.0]), np.array([0.0]), np.array([7.0]), np.array([0.0])
    )[0] == pytest.approx(21.0)


def test_variacao_do_prazo_aumenta_o_estoque_de_seguranca() -> None:
    sem, com = a4.ponto_de_reposicao(
        np.array([2.0, 2.0]), np.array([4.0, 4.0]), np.array([10.0, 10.0]), np.array([0.0, 16.0])
    )
    assert com > sem


def test_demanda_ignora_dias_sem_estoque_no_inicio() -> None:
    """Dia 3 começou zerado: saída 0 não é falta de pedido, é falta de estoque."""
    diario = pd.DataFrame(
        {
            "codigo": ["X"] * 4,
            "dia": pd.date_range("2026-01-01", periods=4),
            "saida": [4, 6, 0, 2],
            "saldo_fim_do_dia": [6, 0, 0, 8],
        }
    )
    resultado = a4.demanda(diario).loc["X"]
    assert resultado["d_ingenua"] == pytest.approx(3.0)  # (4+6+0+2)/4
    # dias com estoque no início: 2 (saldo 6 na véspera) e... o dia 1 não tem véspera,
    # o dia 3 começou em 0 e o dia 4 também. Sobra só o dia 2.
    assert resultado["d"] == pytest.approx(6.0)


def test_prazo_com_poucas_compras_usa_o_de_todas() -> None:
    prazos = pd.DataFrame({"codigo": ["A"] * 4 + ["B"], "prazo_dias": [10, 12, 14, 16, 40]})
    resultado = a4.prazo_de_entrega(prazos, pd.Index(["A", "B", "C"]))
    assert resultado.loc["A", "prazo"] == pytest.approx(13.0)
    assert resultado.loc["B", "prazo"] == pytest.approx(prazos.prazo_dias.mean())  # 1 compra
    assert resultado.loc["C", "compras"] == 0


# ================================================================== SQL
@pytest.mark.integracao
def test_rupturas_viram_episodios_de_dias_consecutivos(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=2)  # T0 = segunda, 05/01/2026

    def retirar(qtd: int, quando: float) -> None:
        chamar_funcao(
            bd,
            "registrar_retirada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=qtd,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(quando),
        )

    retirar(2, 1)  # zera na segunda
    chamar_funcao(
        bd,
        "registrar_entrada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=5,
        p_executado_por=base.estoquista,
        p_ocorrida_em=horas(48 + 2),
        p_observacao="Pedido feito em 2025-12-20",
    )  # chega na quarta
    retirar(5, 96 + 1)  # zera de novo na sexta
    codigo = bd.execute("SELECT codigo FROM core.material_tipo WHERE id = %s", [papel]).fetchone()
    assert codigo is not None
    episodios = bd.execute(
        "SELECT inicio, fim, dias FROM analise.vw_ruptura WHERE codigo = %s ORDER BY inicio",
        [codigo[0]],
    ).fetchall()
    assert episodios[0] == (date(2026, 1, 5), date(2026, 1, 6), 2)  # segunda e terça
    assert episodios[1][0] == date(2026, 1, 9)  # a partir de sexta
    assert len(episodios) == 2
    # Nada antes do cadastro: sem ruptura "fantasma" nos dias anteriores ao material.
    assert min(e[0] for e in episodios) >= date(2026, 1, 5)
    prazo = bd.execute(
        "SELECT pedido_em, prazo_dias FROM analise.vw_prazo_entrega WHERE codigo = %s",
        [codigo[0]],
    ).fetchall()
    assert prazo == [(date(2025, 12, 20), 18)]  # pedido 20/12, recebido 07/01


# ================================================================== conjunto carregado
@pytest.mark.integracao
@pytest.mark.lento
def test_diagnostico_acha_as_calibracoes_plantadas(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    e = engine(banco_teste)
    try:
        diario = a4.ler_diario(e)
        prazos = a4.ler_prazos(e)
    finally:
        e.dispose()
    verdade = json.loads((carga_padrao.pasta / "gabarito_padroes.json").read_text(encoding="utf-8"))
    calibracao = verdade["calibracao_consumo"]
    diario = diario[diario["codigo"].isin(calibracao)]
    prazos = prazos[prazos["codigo"].isin(calibracao)]
    resultado = a4.diagnostico(diario, prazos)
    esperado = pd.Series(calibracao).map(
        {
            "bom": "ADEQUADO",
            "excesso": "EXCESSO",
            "fornecedor_lento": "FORNECEDOR_LENTO",
            "mal_calibrado": "MINIMO_ABAIXO",
        }
    )
    assert (resultado["diagnostico"] == esperado.reindex(resultado.index)).all()
