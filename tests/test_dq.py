"""Qualidade de dados (schema dq): cada regra encontra o problema quando ele existe.

Um "zero ocorrências" só significa algo se a regra comprovadamente acha o problema.
Por isso cada teste injeta uma violação por FORA das funções de regra (INSERT/UPDATE
direto, como faria um cliente com defeito) e confere que a regra certa a registra.
"""

from datetime import date

import pytest

from almox.banco import Conexao, chamar_funcao, engine
from almox.config import ConfigBanco

from .apoio import T0, CargaPadrao, horas, valor
from .cenario import Base, criar_consumo_com_saldo, criar_material, criar_unidades
from .operacoes import retirar

pytestmark = pytest.mark.integracao


def ocorrencias(bd: Conexao, regra: str) -> list[str]:
    """Roda dq.executar() e devolve as referências encontradas pela regra."""
    execucao = valor(bd, "SELECT dq.executar()")
    return [
        referencia
        for (referencia,) in bd.execute(
            "SELECT referencia FROM dq.ocorrencia WHERE execucao_id = %s AND regra = %s",
            [execucao, regra],
        )
    ]


def _mov_consumo_direto(bd: Conexao, base: Base, material: int, antes: int, **extra: object) -> int:
    campos: dict[str, object] = {
        "ocorrida_em": horas(5),
        "tipo": "RETIRADA",
        "material_tipo_id": material,
        "controle": "CONSUMO",
        "variacao": -1,
        "saldo_antes": antes,
        "saldo_depois": antes - 1,
        "pessoa_id": base.pessoa,
        "executado_por": base.equipamentista,
    }
    campos.update(extra)
    colunas = ", ".join(campos)
    marcadores = ", ".join(f"%({c})s" for c in campos)
    comando = f"INSERT INTO core.movimentacao ({colunas}) VALUES ({marcadores}) RETURNING id"  # noqa: S608
    novo = valor(bd, comando, campos)
    assert isinstance(novo, int)
    return novo


def test_regras_cadastradas(bd: Conexao) -> None:
    codigos = [c for (c,) in bd.execute("SELECT codigo FROM dq.regra ORDER BY codigo")]
    assert codigos == [f"DQ{i:02d}" for i in range(1, 11)]


def test_dq01_estado_alterado_por_fora(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    bd.execute(
        "UPDATE core.saldo_consumo SET quantidade = 999 WHERE material_tipo_id = %s", [papel]
    )
    assert f"SALDO {papel}" in ocorrencias(bd, "DQ01")


def test_dq02_saldo_encadeado_quebrado(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    # A anterior terminou em 10; esta diz que começou em 3 (a soma não denuncia isso).
    quebrada = _mov_consumo_direto(bd, base, papel, antes=3)
    assert f"movimentacao {quebrada}" in ocorrencias(bd, "DQ02")


def test_dq03_situacao_encadeada_quebrada(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    (unidade,) = criar_unidades(bd, base, radio)  # termina DISPONIVEL
    quebrada = valor(
        bd,
        "INSERT INTO core.movimentacao (ocorrida_em, tipo, material_tipo_id, controle, "
        "unidade_id, status_anterior, status_novo, executado_por) VALUES (%(t)s, "
        "'MUDANCA_STATUS', %(m)s, 'SERIAL', %(u)s, 'EM_MANUTENCAO', 'DISPONIVEL', %(e)s) "
        "RETURNING id",
        {"t": horas(3), "m": radio, "u": unidade, "e": base.estoquista},
    )
    assert f"movimentacao {quebrada}" in ocorrencias(bd, "DQ03")


def test_dq04_cautela_com_pessoa_transferida(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    (unidade,) = criar_unidades(bd, base, radio)
    retirar(bd, base, unidade, pessoa=base.pessoa2)
    bd.execute(
        "UPDATE core.pessoa SET data_saida = %s WHERE id = %s", [date(2026, 2, 1), base.pessoa2]
    )
    assert f"unidade {unidade}" in ocorrencias(bd, "DQ04")


def test_dq05_retirada_antes_da_pessoa_chegar(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    # pessoa_nova chega em 2026-06-01; a retirada é de janeiro.
    fora = _mov_consumo_direto(bd, base, papel, antes=10, pessoa_id=base.pessoa_nova)
    assert f"movimentacao {fora}" in ocorrencias(bd, "DQ05")


def test_dq06_entrada_lancada_por_equipamentista(bd: Conexao, base: Base) -> None:
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    indevida = _mov_consumo_direto(
        bd, base, papel, antes=10, tipo="ENTRADA", variacao=5, saldo_depois=15, pessoa_id=None
    )
    assert f"movimentacao {indevida}" in ocorrencias(bd, "DQ06")


def test_dq06_perfil_rebaixado_depois_do_lancamento(bd: Conexao, base: Base) -> None:
    """O lançamento foi legítimo, mas o usuário perdeu o perfil depois: revisão."""
    papel = criar_consumo_com_saldo(bd, base, saldo=10)  # entrada inicial pelo estoquista
    bd.execute("UPDATE core.usuario SET perfil = 'CONSULTA' WHERE id = %s", [base.estoquista])
    referencias = ocorrencias(bd, "DQ06")
    entrada = valor(
        bd,
        "SELECT id FROM core.movimentacao WHERE material_tipo_id = %(m)s AND tipo = 'ENTRADA'",
        {"m": papel},
    )
    assert f"movimentacao {entrada}" in referencias


def test_dq07_unidade_sem_entrada(bd: Conexao, base: Base) -> None:
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    unidade = valor(
        bd,
        "INSERT INTO core.unidade_patrimonial (material_tipo_id, bmp, local_id, status) "
        "VALUES (%(m)s, '6543210', %(l)s, 'DISPONIVEL') RETURNING id",
        {"m": radio, "l": base.local},
    )
    assert f"unidade {unidade}" in ocorrencias(bd, "DQ07")


def test_dq08_material_orfao(bd: Conexao, base: Base) -> None:
    orfao = criar_material(bd, base, "SERIAL", prazo_horas=12)
    codigo = valor(bd, "SELECT codigo FROM core.material_tipo WHERE id = %(i)s", {"i": orfao})
    assert f"material {codigo}" in ocorrencias(bd, "DQ08")


@pytest.mark.parametrize("bmp", ["12AB567", "123456", "12345678", " 1234567"])
def test_dq09_bmp_fora_do_formato(bd: Conexao, bmp: str) -> None:
    bd.execute(
        "INSERT INTO staging.carga_planilha (linha, bmp, nomenclatura, local, arquivo) "
        "VALUES (900101, %s, 'Rádio', 'Depósito Central', 't.csv')",
        [bmp],
    )
    assert "planilha linha 900101" in ocorrencias(bd, "DQ09")


@pytest.mark.parametrize(("nome", "local"), [(None, "Depósito"), ("Rádio", "  "), ("", None)])
def test_dq10_campo_obrigatorio_vazio(bd: Conexao, nome: str | None, local: str | None) -> None:
    bd.execute(
        "INSERT INTO staging.carga_planilha (linha, bmp, nomenclatura, local, arquivo) "
        "VALUES (900102, '1234567', %s, %s, 't.csv')",
        [nome, local],
    )
    assert "planilha linha 900102" in ocorrencias(bd, "DQ10")


def test_dados_validos_nao_geram_ocorrencia(bd: Conexao, base: Base) -> None:
    """Controle negativo: o que passa pelas funções de regra não é apontado."""
    papel = criar_consumo_com_saldo(bd, base, saldo=10)
    chamar_funcao(
        bd,
        "registrar_retirada_consumo",
        p_material_tipo_id=papel,
        p_quantidade=2,
        p_pessoa_id=base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(1),
    )
    radio = criar_material(bd, base, "SERIAL", prazo_horas=12)
    (unidade,) = criar_unidades(bd, base, radio, quando=T0)
    retirar(bd, base, unidade)
    execucao = valor(bd, "SELECT dq.executar()")
    mencionados = valor(
        bd,
        "SELECT count(*) FROM dq.ocorrencia o WHERE o.execucao_id = %(e)s AND ("
        " o.referencia IN (SELECT 'movimentacao ' || id FROM core.movimentacao"
        "                  WHERE material_tipo_id IN (%(p)s, %(r)s))"
        " OR o.referencia = 'unidade ' || %(u)s)",
        {"e": execucao, "p": papel, "r": radio, "u": unidade},
    )
    assert mencionados == 0


@pytest.mark.lento
def test_conjunto_carregado_nao_tem_ocorrencias(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> None:
    """Os ~15,7 mil eventos gerados, carregados pelas funções, passam em todas as regras."""
    e = engine(banco_teste)
    try:
        with e.begin() as con:
            execucao = con.exec_driver_sql("SELECT dq.executar()").scalar_one()
            total = con.exec_driver_sql(
                "SELECT ocorrencias FROM dq.execucao WHERE id = %(e)s", {"e": execucao}
            ).scalar_one()
            con.rollback()
    finally:
        e.dispose()
    assert total == 0
