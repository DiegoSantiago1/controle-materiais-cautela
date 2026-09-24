"""Concorrência: operações simultâneas sobre o mesmo saldo ou a mesma unidade.

Aqui as transações são confirmadas de verdade (COMMIT), com várias conexões ao mesmo
tempo, por isso estes testes rodam no banco de testes recriado a cada execução e cada
um cria os próprios materiais.

O que protege: SELECT ... FOR UPDATE dentro das funções. A segunda transação espera a
primeira terminar e só então lê o estado, já atualizado.
"""

import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from almox.banco import Conexao, chamar_funcao, conectar
from almox.config import ConfigBanco

from .apoio import horas, valor
from .cenario import Base, criar_consumo_com_saldo, criar_material, criar_unidades

pytestmark = pytest.mark.integracao


def em_paralelo(
    config: ConfigBanco, quantidade: int, operacao: Callable[[Conexao], object]
) -> Counter[str]:
    """Roda `operacao` em N conexões ao mesmo tempo (liberadas juntas por uma barreira).

    Devolve a contagem de resultados: 'ok' ou o SQLSTATE do erro.
    """
    barreira = threading.Barrier(quantidade)

    def tarefa() -> str:
        with conectar(config) as con:
            barreira.wait(timeout=30)
            try:
                operacao(con)
                con.commit()
                return "ok"
            except psycopg.Error as erro:
                con.rollback()
                return erro.sqlstate or "?"

    with ThreadPoolExecutor(max_workers=quantidade) as executor:
        futuros = [executor.submit(tarefa) for _ in range(quantidade)]
        return Counter(f.result(timeout=60) for f in futuros)


def confirmado[T](config: ConfigBanco, criar: Callable[[Conexao], T]) -> T:
    """Cria dados e faz COMMIT (as outras conexões precisam enxergá-los)."""
    with conectar(config) as con:
        return criar(con)


def sem_divergencias(config: ConfigBanco) -> bool:
    with conectar(config) as con:
        return valor(con, "SELECT count(*) FROM core.vw_divergencia_estado") == 0


def test_segunda_retirada_espera_a_primeira_e_ve_o_saldo_atualizado(
    banco_teste: ConfigBanco, base: Base
) -> None:
    papel = confirmado(banco_teste, lambda con: criar_consumo_com_saldo(con, base, saldo=10))

    def retirar(con: Conexao, qtd: int) -> None:
        chamar_funcao(
            con,
            "registrar_retirada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=qtd,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(1),
        )

    con_a = conectar(banco_teste)
    con_b = conectar(banco_teste)
    pid_b = con_b.info.backend_pid
    resultado_b: list[str] = []
    try:
        retirar(con_a, 8)  # A trava o saldo e ainda não confirmou

        def executar_b() -> None:
            try:
                retirar(con_b, 5)
                con_b.commit()
                resultado_b.append("ok")
            except psycopg.Error as erro:
                con_b.rollback()
                resultado_b.append(erro.sqlstate or "?")

        thread_b = threading.Thread(target=executar_b)
        thread_b.start()

        # Prova de que B está parada esperando a trava de A (e não rodando em paralelo).
        with conectar(banco_teste) as observador:
            observador.autocommit = True
            limite = time.monotonic() + 10
            esperando = False
            while time.monotonic() < limite and not esperando:
                esperando = (
                    valor(
                        observador,
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %(p)s",
                        {"p": pid_b},
                    )
                    == "Lock"
                )
                time.sleep(0.05)
        assert esperando, "a segunda transação deveria estar esperando a trava"
        assert resultado_b == []

        con_a.commit()  # libera a trava; B continua e encontra saldo 2
        thread_b.join(timeout=10)
    finally:
        con_a.close()
        con_b.close()

    assert resultado_b == ["ALM01"]
    with conectar(banco_teste) as con:
        assert (
            valor(
                con,
                "SELECT quantidade FROM core.saldo_consumo WHERE material_tipo_id = %(m)s",
                {"m": papel},
            )
            == 2
        )


def test_vinte_retiradas_simultaneas_de_um_saldo_de_dez(
    banco_teste: ConfigBanco, base: Base
) -> None:
    papel = confirmado(banco_teste, lambda con: criar_consumo_com_saldo(con, base, saldo=10))

    resultados = em_paralelo(
        banco_teste,
        20,
        lambda con: chamar_funcao(
            con,
            "registrar_retirada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=1,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(1),
        ),
    )

    assert resultados == Counter({"ok": 10, "ALM01": 10})
    with conectar(banco_teste) as con:
        linha = con.execute(
            "SELECT s.quantidade, count(m.id) FILTER (WHERE m.tipo = 'RETIRADA'), "
            "min(m.saldo_depois) FILTER (WHERE m.tipo = 'RETIRADA') "
            "FROM core.saldo_consumo s JOIN core.movimentacao m USING (material_tipo_id) "
            "WHERE s.material_tipo_id = %s GROUP BY s.quantidade",
            [papel],
        ).fetchone()
    # Saldo zerado, 10 retiradas, e o saldo registrado desceu até 0 sem pular nem repetir.
    assert linha == (0, 10, 0)
    assert sem_divergencias(banco_teste)


def test_dez_cautelas_simultaneas_da_mesma_unidade(banco_teste: ConfigBanco, base: Base) -> None:
    def criar(con: Conexao) -> int:
        radio = criar_material(con, base, "SERIAL", prazo_horas=12)
        (unidade,) = criar_unidades(con, base, radio)
        return unidade

    unidade = confirmado(banco_teste, criar)

    resultados = em_paralelo(
        banco_teste,
        10,
        lambda con: chamar_funcao(
            con,
            "registrar_retirada_unidade",
            p_unidade_id=unidade,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(1),
        ),
    )

    assert resultados == Counter({"ok": 1, "ALM02": 9})
    with conectar(banco_teste) as con:
        assert (
            valor(
                con,
                "SELECT count(*) FROM core.movimentacao "
                "WHERE unidade_id = %(u)s AND tipo = 'RETIRADA'",
                {"u": unidade},
            )
            == 1
        )
    assert sem_divergencias(banco_teste)


def test_dois_estornos_simultaneos_da_mesma_movimentacao(
    banco_teste: ConfigBanco, base: Base
) -> None:
    def criar(con: Conexao) -> int:
        papel = criar_consumo_com_saldo(con, base, saldo=10)
        mov = chamar_funcao(
            con,
            "registrar_retirada_consumo",
            p_material_tipo_id=papel,
            p_quantidade=4,
            p_pessoa_id=base.pessoa,
            p_executado_por=base.equipamentista,
            p_ocorrida_em=horas(1),
        )
        assert isinstance(mov, int)
        return mov

    mov = confirmado(banco_teste, criar)

    resultados = em_paralelo(
        banco_teste,
        2,
        lambda con: chamar_funcao(
            con,
            "estornar_movimentacao",
            p_movimentacao_id=mov,
            p_executado_por=base.admin,
            p_justificativa="Retirada lançada em duplicidade",
            p_ocorrida_em=horas(2),
        ),
    )

    assert resultados == Counter({"ok": 1, "ALM07": 1})
    assert sem_divergencias(banco_teste)
