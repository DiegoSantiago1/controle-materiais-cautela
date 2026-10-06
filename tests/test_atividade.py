"""Materiais operacionais (almox.complemento) e a atividade de setembro (almox.atividade).

O plano é Python puro e testado sem banco (determinismo, ordem, coerência). A execução é
testada no banco de testes, por cima da carga padrão, numa transação desfeita no fim:
tudo passa pelas funções de regra, e o estado final não pode divergir do histórico.
"""

from collections import Counter
from collections.abc import Iterator
from datetime import datetime, time

import pytest

from almox import atividade as atv
from almox.banco import Conexao, conectar
from almox.complemento import CONSUMOS, MATERIAIS, NOVOS_MILITARES, carregar_complemento
from almox.config import ConfigBanco

from .apoio import CargaPadrao, valor

PESSOAS = list(range(1000, 1040))
OPERADORES = atv.Operadores(equipamentistas=(1, 2, 3, 4), estoquista=5, administrador=6)


@pytest.fixture(scope="module")
def plano() -> list[atv.Evento]:
    return atv.planejar(PESSOAS, OPERADORES)


# ------------------------------------------------------------------ catálogo
def test_catalogo_sem_codigo_nem_nome_repetido() -> None:
    codigos = [m.codigo for m in MATERIAIS] + [c.codigo for c in CONSUMOS]
    nomes = [m.nome.lower() for m in MATERIAIS] + [c.nome.lower() for c in CONSUMOS]
    assert len(set(codigos)) == len(codigos)
    assert len(set(nomes)) == len(nomes)


def test_catalogo_cobre_as_categorias_pedidas() -> None:
    subcategorias = {m.subcategoria for m in MATERIAIS}
    assert {
        "Controle de distúrbios", "Formatura e cerimonial", "Paraquedismo", "Campanha",
        "EPI permanente", "Rádios portáteis", "Acessórios de comunicação",
        "Energia e carregadores",
    } <= subcategorias  # fmt: skip
    assert all(0 <= m.minimo <= m.unidades for m in MATERIAIS)
    assert all(c.minimo <= c.saldo_inicial <= c.maximo for c in CONSUMOS)


def test_novos_militares_com_nome_de_guerra_unico() -> None:
    nomes = [guerra.lower() for _, _, _, guerra, _ in NOVOS_MILITARES]
    matriculas = [m for m, *_ in NOVOS_MILITARES]
    assert len(set(nomes)) == len(nomes)
    assert all(len(m) == 7 and m.isdigit() and m >= "7000000" for m in matriculas)


# ------------------------------------------------------------------ plano (sem banco)
def test_plano_reproduzivel(plano: list[atv.Evento]) -> None:
    assert atv.planejar(PESSOAS, OPERADORES) == plano
    assert atv.planejar(list(reversed(PESSOAS)), OPERADORES) == plano  # ordem não importa


def test_plano_em_ordem_e_dentro_do_mes(plano: list[atv.Evento]) -> None:
    instantes = [e.em for e in plano]
    assert instantes == sorted(instantes)
    assert instantes[0] >= datetime.combine(atv.INICIO, time(0), tzinfo=atv.FUSO)
    assert instantes[-1] <= datetime.combine(atv.FIM, time(23, 59), tzinfo=atv.FUSO)


def test_devolucao_depois_da_retirada_e_uma_vez_so(plano: list[atv.Evento]) -> None:
    retirada = {e.operacao: e for e in plano if isinstance(e, atv.Retirada)}
    devolvidas = Counter(e.de for e in plano if isinstance(e, atv.Devolucao))
    assert max(devolvidas.values()) == 1
    for e in plano:
        if isinstance(e, atv.Devolucao):
            assert e.em > retirada[e.de].em


def test_quem_entrega_e_quem_recebe(plano: list[atv.Evento]) -> None:
    """Só equipamentistas atendem no balcão, e nenhum militar atende a si mesmo."""
    for e in plano:
        if isinstance(e, atv.Retirada | atv.Devolucao):
            assert e.executor in OPERADORES.equipamentistas
        if isinstance(e, atv.Retirada):
            assert e.pessoa in PESSOAS
    retirada = {e.operacao: e for e in plano if isinstance(e, atv.Retirada)}
    trocas = sum(
        1 for e in plano if isinstance(e, atv.Devolucao) and e.executor != retirada[e.de].executor
    )
    assert trocas > 100  # a troca do serviço: quem recebe de volta é outro equipamentista


def test_ha_posse_vencida_no_fim_do_mes(plano: list[atv.Evento]) -> None:
    devolvidas = {e.de for e in plano if isinstance(e, atv.Devolucao)}
    abertas = Counter(
        e.finalidade for e in plano if isinstance(e, atv.Retirada) and e.operacao not in devolvidas
    )
    assert abertas["Desfile de 7 de Setembro"] == 1
    assert abertas["Exercício de campanha"] == 1
    assert abertas["Serviço de dia"] == 4  # o serviço do último dia
    assert abertas["Estágio de sobrevivência"] == 16  # ainda em campo, dentro do prazo


def test_poucos_militares_e_recusado() -> None:
    with pytest.raises(ValueError, match="28 militares"):
        atv.planejar(PESSOAS[:20], OPERADORES)


# ------------------------------------------------------------------ execução (banco)
@pytest.fixture
def com_atividade(
    banco_teste: ConfigBanco, carga_padrao: CargaPadrao
) -> Iterator[tuple[Conexao, atv.Resumo]]:
    """Complemento + atividade sobre a carga padrão, desfeitos no fim (ROLLBACK)."""
    con = conectar(banco_teste)
    try:
        carregar_complemento(con)
        yield con, atv.carregar_atividade(con)
    finally:
        con.rollback()
        con.close()


@pytest.mark.integracao
@pytest.mark.lento
def test_atividade_passa_pelas_regras_sem_divergencia(
    com_atividade: tuple[Conexao, atv.Resumo],
) -> None:
    con, resumo = com_atividade
    assert valor(con, "SELECT count(*) FROM core.vw_divergencia_estado") == 0
    assert resumo.retiradas > 350 and resumo.devolucoes > 350
    assert resumo.avarias >= 20 and resumo.retornos_da_manutencao > 0
    assert resumo.itens_sem_estoque <= 5


@pytest.mark.integracao
@pytest.mark.lento
def test_atividade_deixa_o_que_a_tela_precisa_mostrar(
    com_atividade: tuple[Conexao, atv.Resumo],
) -> None:
    con, _ = com_atividade
    vencidas = valor(
        con,
        "SELECT count(DISTINCT operacao) FROM core.vw_posse "
        "WHERE prazo < now() AND finalidade IN ('Desfile de 7 de Setembro', "
        "'Exercício de campanha')",
    )
    assert vencidas == 2
    # No retrato do fim do mês (o último atendimento simulado), a maior parte da posse está
    # dentro do prazo, como numa unidade real: vencida é exceção (10 a 20% das unidades).
    # Só o que aconteceu até o fim da simulação: outros testes gravam movimentações "agora".
    vencidas_no_retrato = valor(
        con,
        "WITH ate_o_fim AS (SELECT max(ocorrida_em) AS retrato FROM core.movimentacao "
        "WHERE ocorrida_em < '2026-10-02') "
        "SELECT avg((prazo < retrato)::int) FROM core.vw_posse, ate_o_fim "
        "WHERE retirada_em <= retrato",
    )
    assert vencidas_no_retrato is not None and 0.10 <= float(vencidas_no_retrato) <= 0.20
    em_manutencao = valor(
        con,
        "SELECT count(*) FROM core.unidade_patrimonial "
        "WHERE status = 'EM_MANUTENCAO' AND bmp::integer >= 6100001",
    )
    assert isinstance(em_manutencao, int) and em_manutencao > 0
    baixadas = valor(
        con,
        "SELECT count(*) FROM core.unidade_patrimonial "
        "WHERE status = 'BAIXADA' AND bmp::integer >= 6100001",
    )
    assert isinstance(baixadas, int) and baixadas > 0
