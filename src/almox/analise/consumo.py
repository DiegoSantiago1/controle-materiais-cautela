"""A4 — Consumo e ruptura: o mínimo cadastrado protege contra a falta?

Para cada material de consumo, a partir só do histórico:

1. Demanda diária (média d e variância var_d) nos dias em que HAVIA estoque no início do
   dia. A demanda observada é censurada: num dia sem estoque a saída registrada é zero
   porque não havia o que entregar, não porque ninguém pediu. Incluir esses dias
   subestimaria justamente os itens que mais faltam.
2. Prazo de entrega real (média L e variância var_L) das compras (data do pedido na
   observação da entrada). Com menos de 3 compras, usa o prazo de todas as compras.
3. Ponto de reposição = d·L + z·√(L·var_d + d²·var_L): a demanda esperada durante o
   prazo, mais um estoque de segurança que cobre a variação da demanda E a do prazo
   (z = 1,65: ~95% dos ciclos sem falta).
4. Compara com o mínimo cadastrado e com o máximo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import Engine

Z_SERVICO = 1.65  # ~95% de nível de serviço
MIN_COMPRAS = 3  # abaixo disso, o prazo do material é estimado pelo de todas as compras
RAZAO_MINIMO_BAIXO = 0.6  # mínimo abaixo de 60% do ponto de reposição
FATOR_FORNECEDOR_LENTO = 1.5  # prazo médio 50% acima do prazo típico
FRACAO_DIAS_ACIMA_EXCESSO = 0.7  # acima do máximo em 70% dos dias ou mais


def ler_diario(engine: Engine) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM analise.vw_consumo_diario ORDER BY codigo, dia", engine)


def ler_prazos(engine: Engine) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM analise.vw_prazo_entrega ORDER BY codigo, pedido_em", engine)


def ponto_de_reposicao(
    d: np.ndarray,
    var_d: np.ndarray,
    prazo: np.ndarray,
    var_prazo: np.ndarray,
    z: float = Z_SERVICO,
) -> np.ndarray:
    """d·L + z·√(L·var_d + d²·var_L), vetorizado."""
    d, var_d = np.asarray(d, float), np.asarray(var_d, float)
    prazo, var_prazo = np.asarray(prazo, float), np.asarray(var_prazo, float)
    return np.asarray(d * prazo + z * np.sqrt(prazo * var_d + d**2 * var_prazo))


def demanda(diario: pd.DataFrame) -> pd.DataFrame:
    """Demanda por material: média e variância nos dias com estoque no início do dia,
    e também a média ingênua (todos os dias), para mostrar o efeito da censura."""
    base = diario.sort_values(["codigo", "dia"]).copy()
    base["saldo_inicio"] = base.groupby("codigo")["saldo_fim_do_dia"].shift(1)
    com_estoque = base[base["saldo_inicio"] > 0]
    resultado = com_estoque.groupby("codigo").agg(d=("saida", "mean"), var_d=("saida", "var"))
    resultado["d_ingenua"] = base.groupby("codigo")["saida"].mean()
    return resultado


def prazo_de_entrega(prazos: pd.DataFrame, codigos: pd.Index) -> pd.DataFrame:
    """Prazo médio e variância por material; com poucas compras, o de todas."""
    por_material = prazos.groupby("codigo").agg(
        prazo=("prazo_dias", "mean"),
        var_prazo=("prazo_dias", "var"),
        compras=("prazo_dias", "count"),
    )
    geral_media = float(prazos["prazo_dias"].mean())
    geral_var = float(prazos["prazo_dias"].var())
    resultado = por_material.reindex(codigos)
    resultado["compras"] = resultado["compras"].fillna(0).astype(int)
    poucas = resultado["compras"] < MIN_COMPRAS
    resultado.loc[poucas, "prazo"] = geral_media
    resultado.loc[poucas, "var_prazo"] = geral_var
    resultado["prazo_tipico"] = float(prazos["prazo_dias"].median())
    return resultado


def diagnostico(diario: pd.DataFrame, prazos: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por material: demanda, prazo, ponto de reposição, mínimo, rupturas,
    dias acima do máximo e o diagnóstico (em ordem de prioridade)."""
    dem = demanda(diario)
    prz = prazo_de_entrega(prazos, dem.index)
    cadastro = diario.groupby("codigo").agg(
        nome=("nome", "first"),
        minimo=("estoque_minimo", "first"),
        maximo=("estoque_maximo", "first"),
        dias_zerado=("saldo_fim_do_dia", lambda s: int((s == 0).sum())),
    )
    dias_acima = diario.assign(acima=diario["saldo_fim_do_dia"] > diario["estoque_maximo"])
    cadastro["fracao_dias_acima_do_maximo"] = dias_acima.groupby("codigo")["acima"].mean()
    r = cadastro.join(dem).join(prz)
    r["ponto_de_reposicao"] = ponto_de_reposicao(
        r["d"].to_numpy(), r["var_d"].to_numpy(), r["prazo"].to_numpy(), r["var_prazo"].to_numpy()
    )
    r["razao_minimo"] = r["minimo"] / r["ponto_de_reposicao"]
    minimo_baixo = r["razao_minimo"] < RAZAO_MINIMO_BAIXO
    lento = (r["compras"] >= MIN_COMPRAS) & (
        r["prazo"] > FATOR_FORNECEDOR_LENTO * r["prazo_tipico"]
    )
    excesso = r["fracao_dias_acima_do_maximo"] >= FRACAO_DIAS_ACIMA_EXCESSO
    r["diagnostico"] = np.select(
        [minimo_baixo, lento, excesso],
        ["MINIMO_ABAIXO", "FORNECEDOR_LENTO", "EXCESSO"],
        default="ADEQUADO",
    )
    return r
