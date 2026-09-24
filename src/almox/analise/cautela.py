"""A2 — Cautela e atrasos: quem atrasa, onde, e o que é pessoa x processo.

As cautelas vêm da view `analise.vw_cautela` (reconstruídas do histórico com LEAD).
Este módulo separa o atraso "da pessoa" do atraso "do material/processo":

1. Taxa esperada da pessoa = média, nas cautelas DELA, da taxa de atraso geral do tipo
   de material (subcategoria). Quem retira muita ferramenta elétrica (que atrasa muito
   para todo mundo) tem expectativa alta; quem retira rádio, baixa.
2. Intervalo de confiança de Wilson (95%) para a taxa observada. A pessoa só é apontada
   se o LIMITE INFERIOR do intervalo ficar acima da taxa esperada: mesmo no cenário
   mais favorável a ela, atrasa mais do que o material explicaria.

Por que Wilson e não "taxa > X%": 1 atraso em 2 cautelas é 50%, mas não é evidência de
nada. O intervalo de Wilson é largo com poucas observações e estreito com muitas, e
(ao contrário do intervalo "normal") não sai de [0, 1] nem colapsa em 0 ou 100%.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import Engine

MIN_CAUTELAS = 20  # abaixo disso, nenhuma conclusão sobre a pessoa


COLUNAS_DE_DATA = ["retirada_em", "prazo", "devolvida_em"]


def ler_cautelas(engine: Engine) -> pd.DataFrame:
    """Cautelas da view, com datas no horário de Recife (o banco devolve em UTC)."""
    cautelas = pd.read_sql("SELECT * FROM analise.vw_cautela ORDER BY retirada_em", engine)
    for coluna in COLUNAS_DE_DATA:
        cautelas[coluna] = pd.to_datetime(cautelas[coluna], utc=True).dt.tz_convert(
            "America/Recife"
        )
    return cautelas


def wilson(
    sucessos: np.ndarray, total: np.ndarray, z: float = 1.96
) -> tuple[np.ndarray, np.ndarray]:
    """Intervalo de confiança de Wilson para uma proporção (vetorizado).

    centro = (p + z²/2n) / (1 + z²/n);  margem = z·√(p(1-p)/n + z²/4n²) / (1 + z²/n)
    Com n = 0 devolve NaN (não há o que estimar).
    """
    s = np.asarray(sucessos, dtype=float)
    n = np.asarray(total, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = s / n
        denominador = 1 + z**2 / n
        centro = (p + z**2 / (2 * n)) / denominador
        margem = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominador
    inferior = np.where(n > 0, np.clip(centro - margem, 0, 1), np.nan)
    superior = np.where(n > 0, np.clip(centro + margem, 0, 1), np.nan)
    return inferior, superior


def atraso_por_pessoa(cautelas: pd.DataFrame, chave: str = "subcategoria") -> pd.DataFrame:
    """Taxa observada, esperada (pela mistura de materiais) e intervalo de Wilson.

    `apontada` = tem pelo menos MIN_CAUTELAS e o limite inferior de Wilson fica acima
    da taxa esperada.
    """
    base = cautelas[cautelas["situacao"] != "OUTRO"].copy()
    base["atrasada"] = base["atrasada"].astype(bool)
    taxa_do_material = base.groupby(chave)["atrasada"].mean()
    base["esperada"] = base[chave].map(taxa_do_material)
    pessoa = base.groupby(["matricula", "pessoa", "setor"], as_index=False).agg(
        cautelas=("atrasada", "size"),
        atrasadas=("atrasada", "sum"),
        esperada=("esperada", "mean"),
    )
    pessoa["observada"] = pessoa["atrasadas"] / pessoa["cautelas"]
    inferior, superior = wilson(pessoa["atrasadas"].to_numpy(), pessoa["cautelas"].to_numpy())
    pessoa["wilson_inferior"] = inferior
    pessoa["wilson_superior"] = superior
    pessoa["excesso"] = pessoa["observada"] - pessoa["esperada"]
    pessoa["apontada"] = (pessoa["cautelas"] >= MIN_CAUTELAS) & (
        pessoa["wilson_inferior"] > pessoa["esperada"]
    )
    return pessoa.sort_values("excesso", ascending=False).reset_index(drop=True)


def resumo_turno(
    cautelas: pd.DataFrame, subcategoria: str = "Rádios portáteis"
) -> dict[str, float]:
    """Regime de turno: quanto volta no mesmo dia, no dia seguinte, depois."""
    radios = cautelas[
        (cautelas["subcategoria"] == subcategoria) & (cautelas["situacao"] == "DEVOLVIDA")
    ]
    dias = (
        pd.to_datetime(radios["devolvida_em"]).dt.tz_convert("America/Recife").dt.normalize()
        - pd.to_datetime(radios["retirada_em"]).dt.tz_convert("America/Recife").dt.normalize()
    ).dt.days
    return {
        "cautelas": float(len(radios)),
        "mesmo_dia": float((dias == 0).mean()),
        "dia_seguinte": float((dias == 1).mean()),
        "depois": float((dias >= 2).mean()),
    }
