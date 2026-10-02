"""Operação de balcão (migração 0014): retirada e devolução por quantidade, código de
operação, estado na retirada, estoque mínimo e as views de estoque e posse.

Cada regra é testada tentando quebrá-la. Os testes de concorrência confirmam (COMMIT) os
dados, com conexões simultâneas de verdade.
"""

import threading
from uuid import UUID

import psycopg
import pytest

from almox.banco import Conexao, chamar_funcao, conectar
from almox.config import ConfigBanco

from .apoio import espera_erro, valor
from .cenario import Base, criar_consumo_com_saldo, criar_material, criar_unidades

pytestmark = pytest.mark.integracao

CHECK = "23514"


def _retirar(
    bd: Conexao, base: Base, material: int, quantidade: int | None, **extra: object
) -> UUID:
    resultado = chamar_funcao(
        bd,
        "registrar_retirada_lote",
        p_material_tipo_id=material,
        p_quantidade=quantidade,
        p_pessoa_id=extra.pop("pessoa", base.pessoa),
        p_executado_por=extra.pop("executor", base.equipamentista),
        **extra,
    )
    assert isinstance(resultado, UUID)
    return resultado


def _devolver(bd: Conexao, base: Base, unidades: list[int], **extra: object) -> UUID:
    resultado = chamar_funcao(
        bd,
        "registrar_devolucao_lote",
        p_unidades=unidades,
        p_pessoa_id=extra.pop("pessoa", base.pessoa),
        p_executado_por=extra.pop("executor", base.equipamentista),
        **extra,
    )
    assert isinstance(resultado, UUID)
    return resultado


def _movimentos(bd: Conexao, operacao: UUID) -> list[tuple[object, ...]]:
    return bd.execute(
        "SELECT tipo, unidade_id, pessoa_id, executado_por, estado_retirada, estado_devolucao "
        "FROM core.movimentacao WHERE operacao = %s ORDER BY unidade_id",
        [operacao],
    ).fetchall()


def _unidades(bd: Conexao, operacao: UUID) -> list[int]:
    linhas = bd.execute(
        "SELECT unidade_id FROM core.movimentacao WHERE operacao = %s ORDER BY unidade_id",
        [operacao],
    ).fetchall()
    return [int(u) for (u,) in linhas]


@pytest.fixture
def escudo(bd: Conexao, base: Base) -> tuple[int, list[int]]:
    """Material cautelável com 5 unidades disponíveis."""
    material = criar_material(bd, base, "SERIAL", prazo_horas=12)
    return material, criar_unidades(bd, base, material, 5)


# ------------------------------------------------------------------ retirada em lote
def test_retirada_escolhe_as_unidades_e_liga_pela_operacao(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, unidades = escudo
    operacao = _retirar(bd, base, material, 3)
    movimentos = _movimentos(bd, operacao)
    assert [m[1] for m in movimentos] == unidades[:3]  # as de menor id, em ordem
    assert all(m[0] == "RETIRADA" and m[2] == base.pessoa for m in movimentos)
    assert all(m[3] == base.equipamentista for m in movimentos)  # quem entregou
    assert all(m[4] == "BOM" for m in movimentos)
    detentores = bd.execute(
        "SELECT count(*) FROM core.unidade_patrimonial WHERE detentor_id = %s "
        "AND material_tipo_id = %s",
        [base.pessoa, material],
    ).fetchone()
    assert detentores == (3,)


def test_retirada_com_unidades_escolhidas_pelo_bmp(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, unidades = escudo
    escolhidas = [unidades[4], unidades[1]]
    operacao = _retirar(bd, base, material, None, p_unidades=escolhidas)
    assert _unidades(bd, operacao) == sorted(escolhidas)


def test_operacao_informada_e_usada(bd: Conexao, base: Base, escudo: tuple[int, list[int]]) -> None:
    material, _ = escudo
    codigo = UUID("12345678-1234-5678-1234-567812345678")
    assert _retirar(bd, base, material, 2, p_operacao=codigo) == codigo


def test_estoque_insuficiente_nao_retira_nada(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, _ = escudo
    with espera_erro(bd, "ALM01"):
        _retirar(bd, base, material, 6)
    assert valor(bd, "SELECT count(*) FROM core.movimentacao WHERE material_tipo_id = %(m)s "
                 "AND tipo = 'RETIRADA'", {"m": material}) == 0  # fmt: skip


@pytest.mark.parametrize("quantidade", [0, -1, 501, None])
def test_quantidade_invalida(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]], quantidade: int | None
) -> None:
    material, _ = escudo
    with espera_erro(bd, "ALM10"):
        _retirar(bd, base, material, quantidade)


@pytest.mark.parametrize(
    ("lista", "motivo"),
    [([], "vazia"), ([], "repetida"), ([], "nulo"), ([2_000_000_000], "inexistente")],
)
def test_lista_de_unidades_invalida(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]], lista: list[int | None], motivo: str
) -> None:
    material, unidades = escudo
    if motivo == "repetida":
        lista = [unidades[0], unidades[0]]
    elif motivo == "nulo":
        lista = [unidades[0], None]
    with espera_erro(bd, "ALM10"):
        _retirar(bd, base, material, None, p_unidades=lista)


def test_unidade_de_outro_material_e_recusada(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, _ = escudo
    outro = criar_material(bd, base, "SERIAL", prazo_horas=12)
    alheia = criar_unidades(bd, base, outro, 1)
    with espera_erro(bd, "ALM10"):
        _retirar(bd, base, material, None, p_unidades=alheia)


def test_quantidade_diferente_da_lista(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, unidades = escudo
    with espera_erro(bd, "ALM10"):
        _retirar(bd, base, material, 3, p_unidades=unidades[:2])


def test_uma_unidade_indisponivel_cancela_o_lote_inteiro(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, unidades = escudo
    _retirar(bd, base, material, None, p_unidades=[unidades[2]], pessoa=base.pessoa2)
    with espera_erro(bd, "ALM02"):
        _retirar(bd, base, material, None, p_unidades=unidades[:3])
    livres = valor(
        bd,
        "SELECT count(*) FROM core.unidade_patrimonial WHERE material_tipo_id = %(m)s "
        "AND status = 'DISPONIVEL'",
        {"m": material},
    )
    assert livres == 4  # só a unidade da outra pessoa saiu: tudo ou nada


def test_material_nao_cautelavel(bd: Conexao, base: Base) -> None:
    armario = criar_material(bd, base, "SERIAL", prazo_horas=None)
    criar_unidades(bd, base, armario, 2)
    with espera_erro(bd, "ALM02"):
        _retirar(bd, base, armario, 1)


def test_perfil_consulta_nao_retira(bd: Conexao, base: Base, escudo: tuple[int, list[int]]) -> None:
    material, _ = escudo
    with espera_erro(bd, "ALM05"):
        _retirar(bd, base, material, 1, executor=base.consulta)


def test_pessoa_fora_da_unidade(bd: Conexao, base: Base, escudo: tuple[int, list[int]]) -> None:
    material, _ = escudo
    with espera_erro(bd, "ALM03"):
        _retirar(bd, base, material, 1, pessoa=base.pessoa_transferida)


# ------------------------------------------------------------------ estado na retirada
def test_estado_regular_exige_observacao(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, _ = escudo
    with espera_erro(bd, "ALM10"):
        _retirar(bd, base, material, 1, p_estado_retirada="REGULAR")
    operacao = _retirar(
        bd, base, material, 1, p_estado_retirada="REGULAR", p_observacao="Visor riscado"
    )
    assert _movimentos(bd, operacao)[0][4] == "REGULAR"


@pytest.mark.parametrize("estado", ["AVARIADO", "bom", "", "INSERVIVEL"])
def test_estado_de_retirada_invalido(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]], estado: str
) -> None:
    material, _ = escudo
    with espera_erro(bd, "ALM10"):
        _retirar(bd, base, material, 1, p_estado_retirada=estado, p_observacao="x")


def test_estado_de_retirada_so_em_retirada(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    """Mesmo um INSERT direto (sem a função) não grava estado de retirada numa devolução."""
    _, unidades = escudo
    with espera_erro(bd, CHECK):
        bd.execute(
            "INSERT INTO core.movimentacao (ocorrida_em, tipo, material_tipo_id, controle, "
            "unidade_id, status_anterior, status_novo, pessoa_id, executado_por, "
            "estado_retirada) SELECT now(), 'DEVOLUCAO', material_tipo_id, 'SERIAL', id, "
            "'CAUTELADA', 'DISPONIVEL', %s, %s, 'BOM' FROM core.unidade_patrimonial "
            "WHERE id = %s",
            [base.pessoa, base.equipamentista, unidades[0]],
        )


# ------------------------------------------------------------------ consumo
def test_retirada_de_consumo_baixa_o_saldo_com_operacao(bd: Conexao, base: Base) -> None:
    pilha = criar_consumo_com_saldo(bd, base, saldo=20)
    operacao = _retirar(bd, base, pilha, 8)
    assert valor(bd, "SELECT quantidade FROM core.saldo_consumo WHERE material_tipo_id = %(m)s",
                 {"m": pilha}) == 12  # fmt: skip
    linha = bd.execute(
        "SELECT variacao, saldo_antes, saldo_depois FROM core.movimentacao WHERE operacao = %s",
        [operacao],
    ).fetchone()
    assert linha == (-8, 20, 12)


def test_consumo_nao_fica_negativo(bd: Conexao, base: Base) -> None:
    pilha = criar_consumo_com_saldo(bd, base, saldo=5)
    with espera_erro(bd, "ALM01"):
        _retirar(bd, base, pilha, 6)


def test_consumo_nao_tem_lista_de_unidades(bd: Conexao, base: Base) -> None:
    pilha = criar_consumo_com_saldo(bd, base, saldo=5)
    with espera_erro(bd, "ALM02"):
        _retirar(bd, base, pilha, None, p_unidades=[1])


# ------------------------------------------------------------------ devolução em lote
def test_ciclo_retirada_posse_devolucao(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    """A retirada continua no histórico depois da devolução; quem entregou e quem recebeu
    podem ser pessoas diferentes."""
    material, _ = escudo
    retirada = _retirar(bd, base, material, 3)
    unidades = _unidades(bd, retirada)
    devolucao = _devolver(bd, base, unidades[:2], executor=base.estoquista)
    assert [m[0] for m in _movimentos(bd, retirada)] == ["RETIRADA"] * 3
    devolvidas = _movimentos(bd, devolucao)
    assert _unidades(bd, devolucao) == unidades[:2]
    assert all(m[0] == "DEVOLUCAO" and m[3] == base.estoquista for m in devolvidas)
    em_posse = valor(bd, "SELECT count(*) FROM core.vw_posse WHERE operacao = %(o)s",
                     {"o": retirada})  # fmt: skip
    assert em_posse == 1  # devolução parcial: uma continua com a pessoa


def test_devolucao_avariada_vai_para_manutencao(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, _ = escudo
    unidades = _unidades(bd, _retirar(bd, base, material, 2))
    with espera_erro(bd, "ALM10"):  # avariado sem observação
        _devolver(bd, base, unidades, p_estado="AVARIADO")
    _devolver(bd, base, unidades, p_estado="AVARIADO", p_observacao="Alça rompida")
    status = bd.execute(
        "SELECT DISTINCT status FROM core.unidade_patrimonial WHERE id = ANY(%s)", [unidades]
    ).fetchall()
    assert status == [("EM_MANUTENCAO",)]


def test_devolucao_de_unidade_de_outra_pessoa_cancela_tudo(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, _ = escudo
    minhas = _unidades(bd, _retirar(bd, base, material, 1))
    alheias = _unidades(bd, _retirar(bd, base, material, 1, pessoa=base.pessoa2))
    with espera_erro(bd, "ALM04"):
        _devolver(bd, base, minhas + alheias)
    assert valor(bd, "SELECT status FROM core.unidade_patrimonial WHERE id = %(u)s",
                 {"u": minhas[0]}) == "CAUTELADA"  # fmt: skip


def test_devolucao_de_unidade_que_nao_esta_cautelada(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    _, unidades = escudo
    with espera_erro(bd, "ALM02"):
        _devolver(bd, base, [unidades[0]])


@pytest.mark.parametrize("lista", ["vazia", "nulo", "repetida"])
def test_devolucao_com_lista_invalida(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]], lista: str
) -> None:
    _, unidades = escudo
    valores = {"vazia": [], "nulo": [unidades[0], None], "repetida": [unidades[0]] * 2}[lista]
    with espera_erro(bd, "ALM10"):
        _devolver(bd, base, valores)  # type: ignore[arg-type]  # nulo de propósito


# ------------------------------------------------------------------ estoque e posse
def _estoque(bd: Conexao, material: int) -> dict[str, object]:
    cursor = bd.execute("SELECT * FROM core.vw_estoque WHERE material_tipo_id = %s", [material])
    linha = cursor.fetchone()
    assert linha is not None and cursor.description is not None
    return dict(zip([c.name for c in cursor.description], linha, strict=True))


def test_estoque_conta_cada_situacao(bd: Conexao, base: Base) -> None:
    material = criar_material(bd, base, "SERIAL", prazo_horas=12)
    unidades = criar_unidades(bd, base, material, 10)
    _retirar(bd, base, material, None, p_unidades=unidades[:3])
    for unidade, status in [(unidades[3], "EM_MANUTENCAO"), (unidades[4], "NAO_LOCALIZADA"),
                            (unidades[5], "BAIXA_PENDENTE")]:  # fmt: skip
        chamar_funcao(bd, "alterar_status_unidade", p_unidade_id=unidade, p_novo_status=status,
                      p_executado_por=base.admin, p_justificativa="teste")  # fmt: skip
    chamar_funcao(bd, "alterar_status_unidade", p_unidade_id=unidades[5], p_novo_status="BAIXADA",
                  p_executado_por=base.admin, p_justificativa="teste")  # fmt: skip
    e = _estoque(bd, material)
    assert (e["total"], e["disponivel"], e["em_posse"], e["em_manutencao"], e["indisponivel"]) == (
        9, 4, 3, 1, 1)  # fmt: skip
    assert e["situacao"] == "NORMAL"  # sem mínimo definido


@pytest.mark.parametrize(
    ("minimo", "disponiveis", "situacao"),
    [(None, 0, "SEM_ESTOQUE"), (6, 3, "CRITICO"), (6, 4, "ABAIXO_DO_MINIMO"), (6, 6, "NORMAL")],
)
def test_situacao_pelo_minimo(
    bd: Conexao, base: Base, minimo: int | None, disponiveis: int, situacao: str
) -> None:
    material = criar_material(bd, base, "SERIAL", prazo_horas=12)
    bd.execute(
        "UPDATE core.material_tipo SET estoque_minimo = %s WHERE id = %s", [minimo, material]
    )
    if disponiveis:
        criar_unidades(bd, base, material, disponiveis)
    assert _estoque(bd, material)["situacao"] == situacao


def test_estoque_de_consumo_usa_o_saldo(bd: Conexao, base: Base) -> None:
    pilha = criar_consumo_com_saldo(bd, base, saldo=8, minimo=10)
    e = _estoque(bd, pilha)
    assert (e["total"], e["disponivel"], e["em_posse"], e["estoque_minimo"]) == (8, 8, 0, 10)
    assert e["situacao"] == "ABAIXO_DO_MINIMO"


def test_minimo_de_material_de_consumo_fica_no_saldo(bd: Conexao, base: Base) -> None:
    """Uma fonte só para o mínimo de cada controle."""
    pilha = criar_consumo_com_saldo(bd, base, saldo=8)
    with espera_erro(bd, CHECK):
        bd.execute("UPDATE core.material_tipo SET estoque_minimo = 5 WHERE id = %s", [pilha])


def test_minimo_negativo_e_recusado(bd: Conexao, base: Base) -> None:
    material = criar_material(bd, base, "SERIAL", prazo_horas=12)
    with espera_erro(bd, CHECK):
        bd.execute("UPDATE core.material_tipo SET estoque_minimo = -1 WHERE id = %s", [material])


def test_posse_mostra_quem_entregou(bd: Conexao, base: Base, escudo: tuple[int, list[int]]) -> None:
    material, _ = escudo
    operacao = _retirar(bd, base, material, 2, executor=base.estoquista, p_finalidade="Serviço")
    linhas = bd.execute(
        "SELECT p.nome_guerra, v.pessoa_id, v.finalidade, v.entregue_por_guerra "
        "FROM core.vw_posse v JOIN core.usuario u ON u.id = %s "
        "JOIN core.pessoa p ON p.id = u.pessoa_id WHERE v.operacao = %s",
        [base.estoquista, operacao],
    ).fetchall()
    assert len(linhas) == 2
    assert all(guerra == entregue and pessoa == base.pessoa and fin == "Serviço"
               for guerra, pessoa, fin, entregue in linhas)  # fmt: skip


def test_historico_continua_sem_divergencia(
    bd: Conexao, base: Base, escudo: tuple[int, list[int]]
) -> None:
    material, _ = escudo
    unidades = _unidades(bd, _retirar(bd, base, material, 4))
    _devolver(bd, base, unidades[:2])
    assert valor(bd, "SELECT count(*) FROM core.vw_divergencia_estado") == 0


# ------------------------------------------------------------------ concorrência
def test_dois_balcoes_nunca_pegam_a_mesma_unidade(banco_teste: ConfigBanco, base: Base) -> None:
    """Dois equipamentistas pedem 3 de um material com 5 disponíveis, ao mesmo tempo.
    SKIP LOCKED: o segundo não espera o primeiro e não recebe nenhuma unidade dele; como
    só sobram 2, ele recebe "estoque insuficiente" na hora."""
    with conectar(banco_teste) as con:
        material = criar_material(con, base, "SERIAL", prazo_horas=12)
        criar_unidades(con, base, material, 5)

    primeiro = conectar(banco_teste)
    segundo = conectar(banco_teste)
    try:
        _retirar(primeiro, base, material, 3)  # transação aberta, unidades travadas
        segundo.execute("SET lock_timeout = '2s'")  # se esperasse, falharia com 55P03
        with pytest.raises(psycopg.Error) as erro:
            _retirar(segundo, base, material, 3, pessoa=base.pessoa2)
        assert erro.value.sqlstate == "ALM01"
        segundo.rollback()
        assert _retirar(segundo, base, material, 2, pessoa=base.pessoa2)  # as 2 que sobram
        primeiro.commit()
        segundo.commit()
    finally:
        primeiro.close()
        segundo.close()

    with conectar(banco_teste) as con:
        por_pessoa = con.execute(
            "SELECT detentor_id, count(*) FROM core.unidade_patrimonial "
            "WHERE material_tipo_id = %s GROUP BY 1 ORDER BY 2 DESC",
            [material],
        ).fetchall()
        assert por_pessoa == [(base.pessoa, 3), (base.pessoa2, 2)]
        assert valor(con, "SELECT count(*) FROM core.vw_divergencia_estado") == 0


def test_retiradas_simultaneas_em_massa(banco_teste: ConfigBanco, base: Base) -> None:
    """8 conexões pedem 2 unidades cada de um material com 10. No máximo 5 conseguem (pode
    ser menos: duas que travaram 1 unidade cada desistem juntas, e quem passou por elas
    naquele instante também). O que nunca pode acontecer: uma unidade sair duas vezes."""
    with conectar(banco_teste) as con:
        material = criar_material(con, base, "SERIAL", prazo_horas=12)
        criar_unidades(con, base, material, 10)
    barreira = threading.Barrier(8)
    resultados: list[str] = []

    def tarefa() -> None:
        with conectar(banco_teste) as con:
            barreira.wait(timeout=30)
            try:
                _retirar(con, base, material, 2)
                con.commit()
                resultados.append("ok")
            except psycopg.Error as erro:
                con.rollback()
                resultados.append(erro.sqlstate or "?")

    threads = [threading.Thread(target=tarefa) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(resultados) == 8
    assert 1 <= resultados.count("ok") <= 5
    assert set(resultados) <= {"ok", "ALM01"}
    with conectar(banco_teste) as con:
        repetidas = valor(
            con,
            "SELECT count(*) - count(DISTINCT unidade_id) FROM core.movimentacao "
            "WHERE material_tipo_id = %(m)s AND tipo = 'RETIRADA'",
            {"m": material},
        )
        assert repetidas == 0
        retiradas = valor(
            con,
            "SELECT count(*) FROM core.unidade_patrimonial WHERE material_tipo_id = %(m)s "
            "AND status = 'CAUTELADA'",
            {"m": material},
        )
        assert retiradas == 2 * resultados.count("ok")
        assert valor(con, "SELECT count(*) FROM core.vw_divergencia_estado") == 0
