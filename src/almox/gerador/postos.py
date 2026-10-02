"""Posto/graduação e nome de guerra das pessoas fictícias.

Sorteio com um gerador de números aleatórios PRÓPRIO (semente derivada da principal): a
simulação consome exatamente a mesma sequência de antes, então eventos, planilha e todos
os números das análises ficam iguais. Só o arquivo de pessoas ganha as duas colunas; o
manifesto SHA-256 comprova isso.

Distribuição: pirâmide de uma unidade pequena (muitos soldados e cabos, poucos oficiais),
com pelo menos um de cada posto de oficial para aparecerem na tela. Quem opera o sistema
tem o posto coerente com a função: o administrador é oficial, estoquistas e
equipamentistas são sargentos ou cabos.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np

# Sigla -> ordem hierárquica (mesma tabela core.posto_graduacao da migração 0013).
ORDEM = {
    "S2": 1, "S1": 2, "CB": 3, "SGT": 4, "ST": 5,
    "TEN": 6, "CAP": 7, "MAJ": 8, "TEN-CEL": 9, "CEL": 10,
}  # fmt: skip

POSTOS_POR_PERFIL = {
    "ADMINISTRADOR": ("CAP", "TEN"),
    "ESTOQUISTA": ("SGT", "ST"),
    "EQUIPAMENTISTA": ("SGT", "CB"),
    "CONSULTA": ("SGT", "ST"),
}

# Quem não opera o sistema: quotas fixas do topo; o restante é dividido entre S2, S1 e CB.
OFICIAIS = ["CEL", "TEN-CEL", "MAJ", "CAP", "TEN", "TEN"]
GRADUADOS = ["ST", "SGT", "SGT", "SGT", "SGT", "SGT", "SGT", "SGT"]
# Oficiais ficam nos setores administrativos e operacionais, não na guarda.
SETORES_DE_OFICIAL = ("ADM", "OPER", "SAUDE", "TI")

TAMANHO_MAXIMO = 30


class PessoaComPosto(Protocol):
    matricula: str
    nome: str
    setor: str
    posto: str
    nome_guerra: str


class UsuarioDoSistema(Protocol):
    @property
    def matricula(self) -> str: ...
    @property
    def perfil(self) -> str: ...


def atribuir_postos(
    pessoas: Sequence[PessoaComPosto], usuarios: Sequence[UsuarioDoSistema], semente: int
) -> None:
    rng = np.random.default_rng((semente, 13))  # fluxo separado do da simulação
    perfil = {u.matricula: u.perfil for u in usuarios}

    for p in pessoas:
        if p.matricula in perfil:
            opcoes = POSTOS_POR_PERFIL[perfil[p.matricula]]
            p.posto = opcoes[int(rng.integers(len(opcoes)))]

    comuns = [p for p in pessoas if p.matricula not in perfil]
    ordem = [comuns[int(i)] for i in rng.permutation(len(comuns))]
    # Oficiais primeiro, entre quem é dos setores de oficial; depois o resto.
    candidatos = [p for p in ordem if p.setor in SETORES_DE_OFICIAL]
    for p, posto in zip(candidatos, OFICIAIS, strict=False):
        p.posto = posto
    restantes = [p for p in ordem if not p.posto]
    pracas = ["S2", "S1", "CB"]
    quadro = GRADUADOS + [pracas[i % 3] for i in range(max(0, len(restantes) - len(GRADUADOS)))]
    for p, posto in zip(restantes, quadro[: len(restantes)], strict=True):
        p.posto = posto

    atribuir_nomes_de_guerra(pessoas)


def atribuir_nomes_de_guerra(pessoas: Sequence[PessoaComPosto]) -> None:
    """Nome de guerra: o sobrenome. Se já estiver em uso, o mais antigo fica com ele e o
    mais moderno usa o prenome, ou o nome completo. Único na unidade, como na vida real."""
    usados: set[str] = set()
    for p in sorted(pessoas, key=lambda x: (-ORDEM[x.posto], x.matricula)):
        partes = p.nome.split()
        for candidato in (partes[-1], partes[0], p.nome[:TAMANHO_MAXIMO]):
            if candidato.lower() not in usados:
                p.nome_guerra = candidato
                usados.add(candidato.lower())
                break
        else:  # pragma: no cover - nomes completos são únicos no gerador
            raise ValueError(f"sem nome de guerra livre para {p.nome}")
