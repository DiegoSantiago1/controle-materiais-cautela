"""A3 — uso, pico simultâneo, falta, sobra e ABC (view vw_uso_material)."""

import pandas as pd
import pytest

from almox.analise import uso as a3
from almox.banco import Conexao

from .cenario import Base, criar_material, criar_unidades
from .operacoes import alterar, devolver, retirar


def _uso(bd: Conexao, material: int) -> dict[str, object]:
    cursor = bd.execute(
        "SELECT v.* FROM analise.vw_uso_material v JOIN core.material_tipo t "
        "ON t.codigo = v.codigo WHERE t.id = %s",
        [material],
    )
    colunas = [c.name for c in cursor.description or []]
    linha = cursor.fetchone()
    assert linha is not None
    return dict(zip(colunas, linha, strict=True))


@pytest.mark.integracao
def test_pico_e_horas_esgotado_quando_todas_as_unidades_saem(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    u1, u2 = criar_unidades(bd, base, radio, quantidade=2)
    retirar(bd, base, u1, quando=1)
    retirar(bd, base, u2, quando=2, pessoa=base.pessoa2)  # das 2h às 5h: as duas fora
    devolver(bd, base, u1, quando=5)
    devolver(bd, base, u2, quando=6, pessoa=base.pessoa2)
    uso = _uso(bd, radio)
    assert uso["pico_simultaneo"] == 2
    assert float(uso["horas_esgotado"]) == pytest.approx(3.0, abs=0.1)  # type: ignore[arg-type]
    assert uso["cautelas"] == 2 and uso["unidades_usadas"] == 2
    assert 0 < float(uso["utilizacao"]) < 1  # type: ignore[arg-type]


@pytest.mark.integracao
def test_unidade_em_manutencao_sai_da_capacidade(bd: Conexao, base: Base) -> None:
    """Com uma das duas em manutenção, basta a outra sair para o material esgotar."""
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    u1, u2 = criar_unidades(bd, base, radio, quantidade=2)
    alterar(bd, base, u1, "EM_MANUTENCAO", quando=1)
    retirar(bd, base, u2, quando=2)
    devolver(bd, base, u2, quando=6)
    uso = _uso(bd, radio)
    assert uso["pico_simultaneo"] == 1
    assert float(uso["horas_esgotado"]) == pytest.approx(4.0, abs=0.1)  # type: ignore[arg-type]
    assert uso["unidades_paradas"] == 1  # a que foi para a manutenção nunca saiu


@pytest.mark.integracao
def test_baixada_conta_como_desgaste_e_sai_da_carga(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    u1, _u2 = criar_unidades(bd, base, radio, quantidade=2)
    retirar(bd, base, u1, quando=1)
    devolver(bd, base, u1, quando=3, estado_material="INSERVIVEL", observacao="Quebrou")
    alterar(bd, base, u1, "BAIXADA", quando=10)
    uso = _uso(bd, radio)
    assert (uso["unidades_na_carga"], uso["baixadas_no_periodo"]) == (1, 1)


@pytest.mark.integracao
def test_material_sem_uso(bd: Conexao, base: Base) -> None:
    maca = criar_material(bd, base, "SERIAL", prazo_horas=72)
    criar_unidades(bd, base, maca, quantidade=3)
    uso = _uso(bd, maca)
    assert (uso["classe_abc"], uso["cautelas"], uso["unidades_paradas"]) == ("SEM USO", 0, 3)


def test_diagnostico_prioriza_a_falta() -> None:
    uso = pd.DataFrame(
        {
            "horas_esgotado": [100.0, 0.0, 0.0, 200.0],
            "utilizacao": [0.30, 0.01, 0.20, 0.02],
            "cautelas": [50, 3, 40, 10],
        }
    )
    assert a3.diagnostico(uso).tolist() == ["FALTA", "SOBRA", "ADEQUADO", "FALTA"]
