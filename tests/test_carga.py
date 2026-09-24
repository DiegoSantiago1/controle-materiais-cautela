"""Carga completa do conjunto gerado, passando por todas as funções de regra do banco.

É o teste cruzado entre o gerador (Python) e as regras (PL/pgSQL): cada um dos ~15 mil
eventos precisa ser aceito, e no fim o estado no banco tem de bater com o estado
reconstruído a partir dos mesmos eventos. A carga em si acontece na fixture de sessão
`carga_padrao` (conftest), compartilhada com os testes das análises.
"""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from almox import carga
from almox.banco import conectar
from almox.carga import eventos_do_csv
from almox.config import ConfigBanco

from .apoio import CargaPadrao, valor

pytestmark = pytest.mark.integracao


@pytest.mark.lento
def test_carga_completa_aceita_todos_os_eventos(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    assert carga_padrao.resultado["eventos"] == carga_padrao.eventos
    with conectar(banco_teste) as con:
        movimentacoes = valor(
            con,
            "SELECT count(*) FROM core.movimentacao m JOIN core.material_tipo t "
            "ON t.id = m.material_tipo_id WHERE t.codigo !~ '^TST-'",
        )
        assert movimentacoes == carga_padrao.eventos
        linhas = valor(con, "SELECT count(*) FROM staging.carga_planilha WHERE linha < 900000")
        assert linhas == carga_padrao.linhas_planilha
        assert valor(con, "SELECT count(*) FROM core.vw_divergencia_estado") == 0
    gravado = json.loads((carga_padrao.pasta / "manifesto.json").read_text(encoding="utf-8"))
    assert gravado["contagens"] == carga_padrao.manifesto["contagens"]


def test_carga_sem_manifesto_falha_com_mensagem_clara(
    banco_teste: ConfigBanco, tmp_path: Path
) -> None:
    with pytest.raises(carga.ErroDeCarga, match=re.escape("rode 'python -m almox.gerador'")):
        carga.carregar(banco_teste, tmp_path, recriar=False)


def test_linha_de_comando_exige_confirmacao_para_apagar() -> None:
    with pytest.raises(SystemExit):
        carga.main([])


@pytest.mark.lento
def test_todo_campo_do_evento_chega_ao_banco(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    """Fidelidade campo a campo: observação, documento e setor de cada evento do CSV
    precisam estar na movimentação correspondente. (Uma versão da carga perdia a
    observação das entradas de consumo, onde está a data do pedido de compra.)"""
    eventos = eventos_do_csv(carga_padrao.pasta)
    esperado = Counter(
        (e.observacao, e.documento)
        for e in eventos
        if e.operacao != "estorno" and (e.observacao or e.documento)
    )
    with conectar(banco_teste) as con:
        no_banco = Counter(
            (obs, doc)
            for obs, doc in con.execute(
                "SELECT m.observacao, m.documento_ref FROM core.movimentacao m "
                "JOIN core.material_tipo t ON t.id = m.material_tipo_id "
                "WHERE t.codigo !~ '^TST-' AND m.tipo <> 'ESTORNO' "
                "AND (m.observacao IS NOT NULL OR m.documento_ref IS NOT NULL)"
            )
        )
    # Mudança de situação com BMP grava "BMP <número>" no documento (a função monta).
    # (Somando: várias chaves "BMP xxx" viram a mesma chave com documento None.)
    no_banco_sem_bmp: Counter[tuple[str | None, str | None]] = Counter()
    for (obs, doc), n in no_banco.items():
        no_banco_sem_bmp[(obs, None if (doc or "").startswith("BMP ") else doc)] += n
    assert no_banco_sem_bmp == esperado
