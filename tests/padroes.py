"""Medidas dos padrões P1 a P16 sobre um conjunto gerado (usadas pelos testes).

Trabalha só com os eventos e cadastros, como uma análise faria. A única "trapaça"
permitida é conhecer o catálogo (prazo de cada tipo, calibração), que é o gabarito do
próprio gerador.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from almox.gerador import catalogo as cat
from almox.gerador.simulacao import Dataset

TIPOS = {t.codigo: t for t in cat.SERIAIS}


@dataclass(frozen=True)
class Cautela:
    material: str
    unidade: str
    pessoa: str
    saida: datetime
    devolucao: datetime | None
    prazo: datetime

    @property
    def atrasada(self) -> bool:
        return self.devolucao is not None and self.devolucao > self.prazo


def cautelas(d: Dataset) -> list[Cautela]:
    """Pares retirada/devolução por unidade (cautelas estornadas não contam)."""
    estornadas = {e.estorno_de for e in d.eventos if e.operacao == "estorno"}
    abertas: dict[str, tuple[str, str, datetime]] = {}
    resultado: list[Cautela] = []

    def fechar(unidade: str, devolucao: datetime | None) -> None:
        material, pessoa, saida = abertas.pop(unidade)
        prazo_h = TIPOS[material].prazo_h
        assert prazo_h is not None
        resultado.append(
            Cautela(material, unidade, pessoa, saida, devolucao, saida + timedelta(hours=prazo_h))
        )

    for e in d.eventos:
        if e.unidade is None:
            continue
        if e.operacao == "retirada_unidade" and e.seq not in estornadas:
            assert e.pessoa is not None
            abertas[e.unidade] = (e.material, e.pessoa, e.ocorrida_em)
        elif e.operacao == "devolucao_unidade":
            fechar(e.unidade, e.ocorrida_em)
    for unidade in list(abertas):
        fechar(unidade, None)
    return resultado


def taxa(itens: list[bool]) -> float:
    return sum(itens) / len(itens) if itens else 0.0


def saldo_diario(d: Dataset) -> dict[str, dict[date, int]]:
    """Saldo de cada material de consumo no fim de cada dia do período."""
    variacoes: dict[str, list[tuple[datetime, int | None, int]]] = defaultdict(list)
    for e in d.eventos:
        if e.operacao == "entrada_consumo":
            assert e.quantidade is not None
            variacoes[e.material].append((e.ocorrida_em, None, e.quantidade))
        elif e.operacao == "retirada_consumo":
            assert e.quantidade is not None
            variacoes[e.material].append((e.ocorrida_em, None, -e.quantidade))
        elif e.operacao == "ajuste_consumo":
            assert e.quantidade is not None
            variacoes[e.material].append((e.ocorrida_em, e.quantidade, 0))  # contagem absoluta
    por_seq = {e.seq: e for e in d.eventos}
    for e in d.eventos:
        if e.operacao == "estorno" and e.estorno_de is not None:
            original = por_seq[e.estorno_de]
            if original.operacao == "retirada_consumo":
                assert original.quantidade is not None
                variacoes[original.material].append((e.ocorrida_em, None, original.quantidade))
    resultado: dict[str, dict[date, int]] = {}
    dias = [d.inicio + timedelta(days=i) for i in range((d.fim - d.inicio).days + 1)]
    for codigo, lista in variacoes.items():
        lista.sort(key=lambda x: x[0])
        saldo, i, por_dia = 0, 0, {}
        for dia in dias:
            while i < len(lista) and lista[i][0].date() <= dia:
                _, absoluto, delta = lista[i]
                saldo = absoluto if absoluto is not None else saldo + delta
                i += 1
            por_dia[dia] = saldo
        resultado[codigo] = por_dia
    return resultado


def episodios(dias: list[date], folga: int = 3) -> int:
    """Número de episódios: dias próximos (até `folga` dias de distância) viram um só."""
    ordenados = sorted(set(dias))
    return sum(
        1 for i, dia in enumerate(ordenados) if i == 0 or (dia - ordenados[i - 1]).days > folga
    )


def rupturas_por_material(d: Dataset) -> dict[str, tuple[int, int]]:
    """(episódios, dias) com saldo zero no fim do dia, por material de consumo.

    Dias zerados separados por até 3 dias contam como um episódio (fim de semana no meio).
    """
    resultado = {}
    for codigo, por_dia in saldo_diario(d).items():
        zerados = [dia for dia, saldo in por_dia.items() if saldo == 0]
        resultado[codigo] = (episodios(zerados), len(zerados))
    return resultado


def cautelas_por_tipo(d: Dataset) -> Counter[str]:
    return Counter(c.material for c in cautelas(d) if c.saida.date() >= d.inicio)
