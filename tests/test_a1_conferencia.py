"""A1 — conferência da planilha de carga: normalização (SQL), detecção e avaliação."""

import pandas as pd
import pytest

from almox.analise import conferencia as a1
from almox.banco import Conexao, engine
from almox.config import ConfigBanco

from .apoio import CargaPadrao, valor


# ================================================================== avaliação (sem banco)
def _conferencia(**colunas: list[bool]) -> pd.DataFrame:
    base = {coluna: [False, False, False] for coluna in a1.COLUNA_PARA_TIPO}
    base.update(colunas)
    return pd.DataFrame({"linha": [1, 2, 3], **base})


def test_deteccoes_viram_pares_linha_tipo() -> None:
    conf = _conferencia(nome_digitacao=[True, False, True], linha_duplicada=[False, True, False])
    assert a1.deteccoes(conf).to_dict("records") == [
        {"linha": 1, "tipo_erro": "digitacao"},
        {"linha": 2, "tipo_erro": "linha_duplicada"},
        {"linha": 3, "tipo_erro": "digitacao"},
    ]


def test_duas_colunas_do_mesmo_tipo_contam_uma_vez() -> None:
    conf = _conferencia(
        bmp_inexistente=[True, False, False], bmp_trocado_existente=[True, False, False]
    )
    assert len(a1.deteccoes(conf)) == 1


def test_deteccoes_exige_todas_as_colunas() -> None:
    with pytest.raises(ValueError, match="ausentes"):
        a1.deteccoes(pd.DataFrame({"linha": [1], "nome_digitacao": [True]}))


def test_avaliar_conta_acertos_falsos_positivos_e_nao_encontrados() -> None:
    detectado = pd.DataFrame({"linha": [1, 2, 3], "tipo_erro": ["digitacao"] * 3})
    gabarito = pd.DataFrame({"linha": [1, 2, 4, 5], "tipo_erro": ["digitacao"] * 4})
    r = a1.avaliar(detectado, gabarito).loc["digitacao"]
    assert (r.acertos, r.falsos_positivos, r.nao_encontrados) == (2, 1, 2)
    assert r.precisao == pytest.approx(2 / 3, abs=1e-3)
    assert r.revocacao == pytest.approx(2 / 4, abs=1e-3)


def test_metrica_sem_base_e_indefinida_e_nao_zero() -> None:
    """Nenhuma detecção de um tipo que existe: precisão 0/0 é indefinida (NaN)."""
    detectado = pd.DataFrame(
        {"linha": pd.Series([], dtype=int), "tipo_erro": pd.Series([], dtype=str)}
    )
    gabarito = pd.DataFrame({"linha": [7], "tipo_erro": ["linha_duplicada"]})
    r = a1.avaliar(detectado, gabarito).loc["linha_duplicada"]
    assert pd.isna(r.precisao)
    assert r.revocacao == 0


# ================================================================== normalização (SQL)


@pytest.mark.integracao
@pytest.mark.parametrize(
    ("texto", "normalizado"),
    [
        ("Rádio Port.  VHF RP-100,", "RADIO PORTATIL VHF RP 100"),
        ("DEP. CENTRAL", "DEPOSITO CENTRAL"),
        ("  Inst. Adm. ", "INSTALACOES ADMINISTRATIVAS"),
        # Sem ponto não é abreviação: "port" de "2 port as" (texto quebrado) fica como está.
        ("Armário de aço 2 port as", "ARMARIO DE ACO 2 PORT AS"),
        ("", None),
        ("  ,  ", None),
    ],
)
def test_normalizar(bd: Conexao, texto: str, normalizado: str | None) -> None:
    assert valor(bd, "SELECT analise.normalizar(%(t)s)", {"t": texto}) == normalizado


@pytest.mark.integracao
def test_chave_ignora_espacos_quebrados_e_hifen(bd: Conexao) -> None:
    chaves = {
        valor(bd, "SELECT analise.chave(%(t)s)", {"t": t})
        for t in (
            "Rádio portátil VHF RP-100",
            "RADIO PORTATIL VHF RP100",
            "Rá dio portá til VHF RP 100",
        )
    }
    assert chaves == {"RADIOPORTATILVHFRP100"}


# ================================================================== conferência completa
@pytest.mark.integracao
@pytest.mark.lento
def test_conferencia_acerta_todos_os_tipos_no_conjunto_padrao(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    """Na semente padrão, a detecção acerta 100% (medido também em outras 7 sementes, com
    duas exceções documentadas: artefato de extração combinado com outro erro na mesma
    palavra)."""
    e = engine(banco_teste)
    try:
        conferencia = a1.ler_conferencia(e)
        gabarito = a1.ler_gabarito(e)
    finally:
        e.dispose()
    conferencia = conferencia[conferencia["linha"] < 900_000]  # só a planilha carregada
    resultado = a1.avaliar(a1.deteccoes(conferencia), gabarito)
    assert set(resultado.index) == set(a1.PADRAO_DO_TIPO)
    assert (resultado["precisao"] == 1).all(), resultado
    assert (resultado["revocacao"] == 1).all(), resultado


@pytest.mark.integracao
@pytest.mark.lento
def test_planilha_corrigida_tem_nome_e_bmp_do_cadastro(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    e = engine(banco_teste)
    try:
        conferencia = a1.ler_conferencia(e)
        gabarito_linha = pd.read_sql(
            "SELECT g.linha, g.bmp_correto, t.nome FROM staging.gabarito_linha g "
            "JOIN core.material_tipo t ON t.codigo = g.material_codigo",
            e,
        )
    finally:
        e.dispose()
    corrigida = a1.planilha_corrigida(conferencia[conferencia["linha"] < 900_000])
    assert corrigida["linha"].is_unique
    assert len(corrigida) == carga_padrao.linhas_planilha - int(
        conferencia["linha_duplicada"].sum()
    )
    junto = corrigida.merge(gabarito_linha, on="linha")
    assert (junto["nome_corrigido"] == junto["nome"]).all()
    # BMP: corrigido quando havia base (o ausente por erro fica para verificação humana).
    com_bmp = junto[junto["bmp_corrigido"].notna()]
    assert (com_bmp["bmp_corrigido"] == com_bmp["bmp_correto"]).all()
