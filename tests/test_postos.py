"""Posto/graduação e nome de guerra (migração 0013 e almox.gerador.postos).

O banco garante o formato (posto existente, nome de guerra único entre quem está na
unidade); o gerador garante a coerência (quem opera o sistema tem o posto da função) sem
mudar nenhum evento da simulação, que é o que sustenta os números das análises.
"""

from collections import Counter
from datetime import date

import pytest

from almox.banco import Conexao
from almox.gerador import catalogo as cat
from almox.gerador.postos import ORDEM, POSTOS_POR_PERFIL
from almox.gerador.simulacao import Dataset, Simulacao, gerar

from .apoio import espera_erro, valor
from .cenario import Base

CHECK, UNIQUE, FK, NOT_NULL = "23514", "23505", "23503", "23502"

POSTOS_PEDIDOS = ["S2", "S1", "CB", "SGT", "ST", "TEN", "CAP", "MAJ", "TEN-CEL", "CEL"]


def _inserir_pessoa(
    bd: Conexao,
    base: Base,
    matricula: str,
    guerra: str,
    posto: str = "S1",
    saida: str | None = None,
) -> None:
    bd.execute(
        "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, data_saida, "
        "posto_graduacao, nome_guerra) VALUES (%s, %s, %s, '2020-01-01', %s, %s, %s)",
        [matricula, f"Pessoa {matricula}", base.setor, saida, posto, guerra],
    )


# ------------------------------------------------------------------ banco
@pytest.mark.integracao
def test_postos_na_ordem_hierarquica(bd: Conexao) -> None:
    linhas = bd.execute("SELECT sigla FROM core.posto_graduacao ORDER BY ordem").fetchall()
    assert [s for (s,) in linhas] == POSTOS_PEDIDOS
    assert list(ORDEM) == POSTOS_PEDIDOS  # o gerador usa a mesma tabela


@pytest.mark.integracao
def test_posto_inexistente_e_recusado(bd: Conexao, base: Base) -> None:
    with espera_erro(bd, FK):
        _inserir_pessoa(bd, base, "3000001", "Inexistente", posto="3S")


@pytest.mark.integracao
@pytest.mark.parametrize("coluna", ["posto_graduacao", "nome_guerra"])
def test_posto_e_nome_de_guerra_obrigatorios(bd: Conexao, base: Base, coluna: str) -> None:
    valores: dict[str, str | None] = {"posto_graduacao": "S1", "nome_guerra": "Fulano"}
    valores[coluna] = None
    with espera_erro(bd, NOT_NULL):
        bd.execute(
            "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, posto_graduacao, "
            "nome_guerra) VALUES ('3000002', 'Fulano', %s, '2020-01-01', %s, %s)",
            [base.setor, valores["posto_graduacao"], valores["nome_guerra"]],
        )


@pytest.mark.integracao
@pytest.mark.parametrize("guerra", ["", " Souza", "Souza ", "Sou  za", "x" * 31])
def test_nome_de_guerra_com_formato_invalido(bd: Conexao, base: Base, guerra: str) -> None:
    with espera_erro(bd, CHECK):
        _inserir_pessoa(bd, base, "3000003", guerra)


@pytest.mark.integracao
def test_nome_de_guerra_unico_entre_quem_esta_na_unidade(bd: Conexao, base: Base) -> None:
    _inserir_pessoa(bd, base, "3000004", "Teste Único")
    with espera_erro(bd, UNIQUE):
        _inserir_pessoa(bd, base, "3000005", "TESTE ÚNICO")  # maiúsculas não diferenciam


@pytest.mark.integracao
def test_quem_ja_saiu_libera_o_nome_de_guerra(bd: Conexao, base: Base) -> None:
    _inserir_pessoa(bd, base, "3000006", "Teste Saída", saida="2024-01-01")
    _inserir_pessoa(bd, base, "3000007", "Teste Saída")
    total = valor(bd, "SELECT count(*) FROM core.pessoa WHERE nome_guerra = 'Teste Saída'")
    assert total == 2


@pytest.mark.integracao
def test_power_bi_ve_posto_e_nome_de_guerra(bd: Conexao) -> None:
    colunas = {
        c
        for (c,) in bd.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'bi' AND table_name = 'dim_pessoa'"
        ).fetchall()
    }
    assert {"posto_graduacao", "posto_graduacao_nome", "posto_ordem", "nome_guerra"} <= colunas


# ------------------------------------------------------------------ gerador
@pytest.fixture(scope="module")
def dados() -> Dataset:
    return gerar()


def test_todos_tem_posto_valido_e_nome_de_guerra(dados: Dataset) -> None:
    for p in dados.pessoas:
        assert p.posto in ORDEM, p
        assert 1 <= len(p.nome_guerra) <= 30, p


def test_nome_de_guerra_unico(dados: Dataset) -> None:
    nomes = Counter(p.nome_guerra.lower() for p in dados.pessoas)
    assert max(nomes.values()) == 1


def test_quem_opera_o_sistema_tem_o_posto_da_funcao(dados: Dataset) -> None:
    pessoa = {p.matricula: p for p in dados.pessoas}
    for u in dados.usuarios:
        assert pessoa[u.matricula].posto in POSTOS_POR_PERFIL[u.perfil], u


def test_piramide_de_uma_unidade_pequena(dados: Dataset) -> None:
    """Muitos soldados e cabos, poucos oficiais, e pelo menos um de cada oficial superior."""
    postos = Counter(p.posto for p in dados.pessoas)
    pracas = postos["S2"] + postos["S1"] + postos["CB"]
    oficiais = sum(postos[s] for s in ("TEN", "CAP", "MAJ", "TEN-CEL", "CEL"))
    assert pracas > oficiais
    assert all(postos[s] >= 1 for s in ("MAJ", "TEN-CEL", "CEL"))


def test_postos_nao_mudam_os_eventos(dados: Dataset) -> None:
    """O sorteio dos postos usa um gerador próprio: a simulação é idêntica com ou sem ele.
    É o que mantém todos os números das análises."""
    sem_postos = Simulacao(cat.SEMENTE_PADRAO, date.fromisoformat(cat.ANCORA_PADRAO)).executar()
    assert sem_postos.eventos == dados.eventos


def test_postos_reproduziveis(dados: Dataset) -> None:
    de_novo = gerar()
    assert [(p.posto, p.nome_guerra) for p in de_novo.pessoas] == [
        (p.posto, p.nome_guerra) for p in dados.pessoas
    ]
