"""Carga completa do conjunto gerado, passando por todas as funções de regra do banco.

É o teste cruzado entre o gerador (Python) e as regras (PL/pgSQL): cada um dos ~15 mil
eventos precisa ser aceito, e no fim o estado no banco tem de bater com o estado que o
gerador calculou. Leva cerca de um minuto (marcado como `lento`).
"""

import json
import re
from pathlib import Path

import pytest

from almox import carga
from almox.banco import conectar
from almox.config import ConfigBanco
from almox.gerador.planilha import gerar_planilha
from almox.gerador.saida import gravar
from almox.gerador.simulacao import gerar

from .apoio import valor

pytestmark = [pytest.mark.integracao, pytest.mark.lento]


def test_carga_completa_aceita_todos_os_eventos(banco_teste: ConfigBanco, tmp_path: Path) -> None:
    dados = gerar()
    planilha = gerar_planilha(dados)
    manifesto = gravar(dados, planilha, tmp_path)

    # Sem recriar: os cadastros do conjunto convivem com os dos outros testes (códigos,
    # matrículas e BMPs em faixas diferentes) no banco de testes.
    resultado = carga.carregar(banco_teste, tmp_path, recriar=False)

    assert resultado["eventos"] == len(dados.eventos)
    with conectar(banco_teste) as con:
        movimentacoes = valor(
            con,
            "SELECT count(*) FROM core.movimentacao m JOIN core.material_tipo t "
            "ON t.id = m.material_tipo_id WHERE t.codigo !~ '^TST-'",
        )
        assert movimentacoes == len(dados.eventos)
        assert valor(con, "SELECT count(*) FROM staging.carga_planilha") == len(planilha)
        assert valor(con, "SELECT count(*) FROM core.vw_divergencia_estado") == 0
    contagens = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))["contagens"]
    assert contagens == manifesto["contagens"]


def test_carga_sem_manifesto_falha_com_mensagem_clara(
    banco_teste: ConfigBanco, tmp_path: Path
) -> None:
    with pytest.raises(carga.ErroDeCarga, match=re.escape("rode 'python -m almox.gerador'")):
        carga.carregar(banco_teste, tmp_path, recriar=False)


def test_linha_de_comando_exige_confirmacao_para_apagar() -> None:
    with pytest.raises(SystemExit):
        carga.main([])
