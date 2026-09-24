"""A1 — Conferência da planilha de carga contra o cadastro.

A detecção é feita pela view `analise.vw_conferencia_planilha` (SQL). Este módulo:
- lê a view e o gabarito para DataFrames;
- transforma as colunas de problema (uma por tipo) em pares (linha, tipo de erro);
- mede o acerto por tipo (precisão e revocação) contra o gabarito;
- monta a planilha corrigida sugerida.

Precisão: das linhas que a conferência apontou, quantas tinham mesmo o erro.
Revocação: das linhas que tinham o erro, quantas a conferência encontrou.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine

# Coluna da view -> tipo de erro no gabarito (staging.gabarito_erro.tipo_erro).
COLUNA_PARA_TIPO = {
    "linha_duplicada": "linha_duplicada",
    "nome_variante": "nomenclatura_variante",
    "nome_artefato_extracao": "artefato_extracao",
    "nome_digitacao": "digitacao",
    "bmp_ausente_legitimo": "bmp_ausente_legitimo",
    "bmp_ausente_erro": "bmp_ausente_erro",
    "bmp_inexistente": "bmp_digito_trocado",  # o BMP escrito não existe
    "bmp_trocado_existente": "bmp_digito_trocado",  # caiu no BMP de outra unidade
    "serie_divergente": "serie_duplicada",
    "local_variante": "local_variante",
    "divergencia_historico": "divergencia_historico",
    "baixa_com_detentor": "baixa_com_detentor",
}

PADRAO_DO_TIPO = {
    "nomenclatura_variante": "P12",
    "digitacao": "P13",
    "artefato_extracao": "P13",
    "bmp_ausente_legitimo": "P14",
    "bmp_ausente_erro": "P14",
    "bmp_digito_trocado": "P14",
    "serie_duplicada": "P15",
    "linha_duplicada": "P15",
    "local_variante": "P16",
    "divergencia_historico": "P16",
    "baixa_com_detentor": "P16",
}


def ler_conferencia(engine: Engine) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM analise.vw_conferencia_planilha ORDER BY linha", engine)


def ler_gabarito(engine: Engine) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT linha, tipo_erro FROM staging.gabarito_erro ORDER BY linha, tipo_erro", engine
    )


def deteccoes(conferencia: pd.DataFrame) -> pd.DataFrame:
    """Colunas booleanas de problema -> uma linha por (linha da planilha, tipo de erro)."""
    colunas = list(COLUNA_PARA_TIPO)
    ausentes = set(colunas) - set(conferencia.columns)
    if ausentes:
        raise ValueError(f"colunas de problema ausentes na conferência: {sorted(ausentes)}")
    longo = conferencia.melt(
        id_vars="linha", value_vars=colunas, var_name="coluna", value_name="ok"
    )
    marcadas = longo[longo["ok"].fillna(False).astype(bool)]
    return (
        marcadas.assign(tipo_erro=marcadas["coluna"].map(COLUNA_PARA_TIPO))[["linha", "tipo_erro"]]
        .drop_duplicates()
        .sort_values(["linha", "tipo_erro"])
        .reset_index(drop=True)
    )


def avaliar(detectado: pd.DataFrame, gabarito: pd.DataFrame) -> pd.DataFrame:
    """Precisão e revocação por tipo de erro.

    Uma detecção é acerto (verdadeiro positivo) se o gabarito tem o mesmo par
    (linha, tipo). Tipos que aparecem em só um dos lados entram com zero do outro.
    """
    chave = ["linha", "tipo_erro"]
    juntos = (
        detectado[chave]
        .drop_duplicates()
        .merge(gabarito[chave].drop_duplicates(), on=chave, how="outer", indicator=True)
    )
    contagem = pd.crosstab(juntos["tipo_erro"], juntos["_merge"]).reindex(
        columns=["both", "left_only", "right_only"], fill_value=0
    )
    resultado = pd.DataFrame(
        {
            "acertos": contagem["both"],
            "falsos_positivos": contagem["left_only"],
            "nao_encontrados": contagem["right_only"],
        }
    )
    resultado["detectados"] = resultado["acertos"] + resultado["falsos_positivos"]
    resultado["no_gabarito"] = resultado["acertos"] + resultado["nao_encontrados"]
    resultado["precisao"] = _razao(resultado["acertos"], resultado["detectados"])
    resultado["revocacao"] = _razao(resultado["acertos"], resultado["no_gabarito"])
    resultado.insert(0, "padrao", resultado.index.map(PADRAO_DO_TIPO))
    resultado.index.name = "tipo_erro"
    return resultado[
        [
            "padrao",
            "no_gabarito",
            "detectados",
            "acertos",
            "falsos_positivos",
            "nao_encontrados",
            "precisao",
            "revocacao",
        ]
    ].sort_values(["padrao", "tipo_erro"])


def _razao(numerador: pd.Series, denominador: pd.Series) -> pd.Series:
    """Divisão com 0/0 = NaN (métrica indefinida, e não 0 nem 1)."""
    return (numerador / denominador.where(denominador > 0)).round(3)


def planilha_corrigida(conferencia: pd.DataFrame) -> pd.DataFrame:
    """Planilha como deveria estar: sem linhas duplicadas, nome e BMP do cadastro.

    Só corrige o que a conferência tem base para corrigir: nome pelo material mais
    parecido, BMP pela unidade de BMP mais próximo (dígito trocado). O resto fica
    marcado para verificação humana (`verificar`), com o motivo.
    """
    base = conferencia[~conferencia["linha_duplicada"]].copy()
    base["nome_corrigido"] = base["nome_correto"]
    bmp_errado = base["bmp_inexistente"] | base["bmp_trocado_existente"]
    base["bmp_corrigido"] = base["bmp"].where(~bmp_errado, base["bmp_provavel"])
    motivos = {
        "bmp_ausente_erro": "BMP em branco (item já tombado)",
        "divergencia_historico": "planilha diz localizado; histórico diz cautelado",
        "baixa_com_detentor": "marcado para descarga, mas está cautelado",
        "serie_divergente": "número de série diferente do cadastro",
    }
    verificar = pd.Series("", index=base.index)
    for coluna, texto in motivos.items():
        verificar = verificar.where(~base[coluna].astype(bool), verificar + texto + "; ")
    sem_vizinho = base["bmp_inexistente"] & base["bmp_provavel"].isna()
    verificar = verificar.where(~sem_vizinho, verificar + "BMP inexistente sem correspondente; ")
    base["verificar"] = verificar.str.rstrip("; ")
    return base[
        [
            "linha",
            "bmp",
            "bmp_corrigido",
            "nomenclatura",
            "nome_corrigido",
            "numero_serie",
            "local",
            "situacao",
            "verificar",
        ]
    ].reset_index(drop=True)
