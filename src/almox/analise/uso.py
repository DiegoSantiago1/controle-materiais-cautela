"""A3 — Uso e ociosidade: o que sobra, o que falta e o que se desgasta.

Os números vêm da view `analise.vw_uso_material` (linhas do tempo de capacidade e de
unidades fora, construídas do histórico com somas acumuladas). Aqui ficam a leitura e
a classificação de cada tipo em um quadro de decisão.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine

# Limiares do quadro de decisão (explícitos, para poderem ser discutidos):
HORAS_ESGOTADO_FALTA = 48.0  # mais de 2 dias sem nenhuma unidade na prateleira
UTILIZACAO_SOBRA = 0.05  # menos de 5% das horas-unidade em uso


def ler_uso(engine: Engine) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM analise.vw_uso_material ORDER BY cautelas DESC", engine)


def diagnostico(uso: pd.DataFrame) -> pd.Series:
    """FALTA (esgota com frequência), SOBRA (parado ou quase), ADEQUADO.

    Falta tem prioridade: um tipo pode ter unidades paradas e ainda assim esgotar (as
    paradas não circulam), e o problema a resolver primeiro é a falta.
    """
    falta = uso["horas_esgotado"] > HORAS_ESGOTADO_FALTA
    sobra = (uso["cautelas"] == 0) | (uso["utilizacao"].fillna(0) < UTILIZACAO_SOBRA)
    resultado = pd.Series("ADEQUADO", index=uso.index)
    resultado = resultado.where(~sobra, "SOBRA")
    return resultado.where(~falta, "FALTA")
