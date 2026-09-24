"""Planilha de conferência de carga "suja" (P12 a P16) e o gabarito dos erros.

1. Reconstrói o estado final de cada unidade reproduzindo os eventos.
2. Monta a planilha limpa: uma linha por unidade ainda na carga (as baixadas saem).
3. Injeta erros com taxas conhecidas, guardando no gabarito o valor correto de cada um.

Os tipos de erro imitam os que aparecem em planilhas reais de conferência: o mesmo item
escrito de vários jeitos, digitação, texto quebrado por extração de PDF, número de
patrimônio ausente ou com dígito trocado, número de série repetido, local escrito de
várias formas, e divergência entre a planilha e o histórico de cautelas.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from almox.gerador import catalogo as cat
from almox.gerador.simulacao import Dataset, Evento


@dataclass(frozen=True)
class EstadoUnidade:
    status: str
    detentor: str | None
    bmp: str | None


STATUS_APOS_DEVOLUCAO = {
    "BOM": "DISPONIVEL",
    "AVARIADO": "EM_MANUTENCAO",
    "INSERVIVEL": "BAIXA_PENDENTE",
}


def _obrigatorio[T](valor: T | None, campo: str, evento: Evento) -> T:
    """Devolve o valor, ou falha dizendo qual evento veio sem o campo."""
    if valor is None:
        raise ValueError(f"evento {evento.seq} ({evento.operacao}) sem {campo}")
    return valor


def estado_final(eventos: Sequence[Evento]) -> dict[str, EstadoUnidade]:
    """Estado de cada unidade na data-âncora, reproduzindo os eventos em ordem.

    Mesmas regras das funções do banco; a carga confere que o resultado bate.
    """
    historico: dict[str, list[EstadoUnidade]] = {}
    por_seq = {e.seq: e for e in eventos}
    for e in eventos:
        if e.operacao == "entrada_unidade":
            status = "DISPONIVEL" if e.bmp else "AGUARDANDO_TOMBAMENTO"
            historico[_obrigatorio(e.unidade, "unidade", e)] = [EstadoUnidade(status, None, e.bmp)]
            continue
        if e.operacao == "estorno":
            original = por_seq[_obrigatorio(e.estorno_de, "estorno_de", e)]
            if original.unidade is not None:
                historico[original.unidade].pop()  # volta ao estado anterior à original
            continue
        if e.unidade is None:
            continue  # movimentação de consumo
        atual = historico[e.unidade][-1]
        if e.operacao == "retirada_unidade":
            novo = EstadoUnidade("CAUTELADA", e.pessoa, atual.bmp)
        elif e.operacao == "devolucao_unidade":
            status = STATUS_APOS_DEVOLUCAO[_obrigatorio(e.estado, "estado", e)]
            novo = EstadoUnidade(status, None, atual.bmp)
        elif e.operacao == "alterar_status":
            novo_status = _obrigatorio(e.novo_status, "novo_status", e)
            novo = EstadoUnidade(novo_status, None, e.bmp or atual.bmp)
        else:
            raise ValueError(f"operação inesperada para unidade: {e.operacao}")
        historico[e.unidade].append(novo)
    return {ref: estados[-1] for ref, estados in historico.items()}


@dataclass
class Linha:
    unidade_ref: str
    material: str
    bmp: str
    nomenclatura: str
    numero_serie: str
    local: str
    situacao: str
    observacao: str = ""
    local_correto: str = ""
    duplicata_de: int | None = None  # índice (0-based) da linha original
    erros: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    # (padrão, tipo_erro, campo, valor_na_planilha, valor_correto)


SITUACAO = {
    "DISPONIVEL": "LOCALIZADO",
    "CAUTELADA": "CAUTELADO",
    "EM_MANUTENCAO": "EM MANUTENÇÃO",
    "NAO_LOCALIZADA": "NÃO ENCONTRADO",
    "BAIXA_PENDENTE": "DESCARGA",
    "AGUARDANDO_TOMBAMENTO": "SEM BMP - RECÉM ADQUIRIDO",
}

ABREVIACOES = {
    "Portátil": "Port.",
    "portátil": "port.",
    "Depósito": "Dep.",
    "Reserva": "Res.",
    "Equipamentos": "Equip.",
    "Ferramentas": "Ferram.",
    "Instalações": "Inst.",
    "Administrativas": "Adm.",
    "Informática": "Inform.",
    "extensível": "ext.",
    "recarregável": "recarreg.",
    "sinalização": "sinaliz.",
    "multimídia": "multim.",
}


def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


class GeradorPlanilha:
    def __init__(self, dataset: Dataset, semente: int) -> None:
        self.d = dataset
        # Semente derivada: a planilha não altera a sequência aleatória da simulação.
        self.rng = np.random.default_rng([semente, 16])
        self.pessoas = {p.matricula: p for p in dataset.pessoas}
        self.tipos = {t.codigo: t for t in cat.SERIAIS}

    # ------------------------------------------------------------ planilha limpa
    def linhas_limpas(self) -> list[Linha]:
        estados = estado_final(self.d.eventos)
        linhas = []
        for unidade in sorted(self.d.unidades, key=lambda u: (u.codigo, u.bmp or "~", u.ref)):
            estado = estados[unidade.ref]
            if estado.status == "BAIXADA":
                continue  # saiu da carga
            if estado.detentor is not None:  # só unidades cauteladas têm detentor
                local = f"Com {self.pessoas[estado.detentor].nome}"
            else:
                local = unidade.local
            linhas.append(
                Linha(
                    unidade_ref=unidade.ref,
                    material=unidade.codigo,
                    bmp=estado.bmp or "",
                    nomenclatura=self.tipos[unidade.codigo].nome,
                    numero_serie=unidade.serie or "",
                    local=local,
                    situacao=SITUACAO[estado.status],
                    local_correto=local,
                )
            )
        return linhas

    # ------------------------------------------------------------ utilidades
    def _escolher[T](self, itens: list[T]) -> T:
        return itens[int(self.rng.integers(0, len(itens)))]

    def _peso(self, linha: Linha) -> float:
        """Peso da linha na chance de erro: o local problemático pesa mais (P16)."""
        if self.tipos[linha.material].local == cat.LOCAL_CONCENTRA_ERROS:
            return cat.MULTIPLICADOR_LOCAL_ERROS
        return 1.0

    def _sortear(self, linhas: list[Linha], taxa: float, elegivel: list[bool]) -> list[int]:
        """Sorteia as linhas que recebem um erro.

        `taxa` é a fração de TODAS as linhas: o número esperado de erros é taxa x N,
        mesmo quando só parte das linhas é elegível (ex.: só quem tem número de série).
        Por isso os pesos são normalizados pela soma dos pesos das ELEGÍVEIS:
            p_i = taxa * N * peso_i / soma(peso das elegíveis)
        """
        pesos = [
            self._peso(linha) if ok else 0.0 for linha, ok in zip(linhas, elegivel, strict=True)
        ]
        soma = sum(pesos)
        if soma == 0:
            return []
        esperado = taxa * len(linhas)
        return [
            i
            for i, peso in enumerate(pesos)
            if peso > 0 and self.rng.random() < min(1.0, esperado * peso / soma)
        ]

    @staticmethod
    def _registrar(
        linha: Linha, padrao: str, tipo: str, campo: str, errado: str, certo: str
    ) -> None:
        linha.erros.append((padrao, tipo, campo, errado, certo))

    # ------------------------------------------------------------ transformações de texto
    def _variante_nome(self, nome: str) -> str:
        opcoes = [
            nome.upper(),
            sem_acento(nome),
            sem_acento(nome).upper(),
            nome.replace("-", "").replace(",", ""),
            " ".join(ABREVIACOES.get(p, p) for p in nome.split()),
            nome.lower(),
            nome + ",",
            nome.replace(" ", "  ", 1),
        ]
        variantes = [v for v in opcoes if v != nome]
        return self._escolher(variantes)

    def _digitacao(self, texto: str) -> str:
        letras = [i for i, c in enumerate(texto) if c.isalpha()]
        i = self._escolher(letras[1:-1] or letras)
        if self.rng.random() < 0.5 and i + 1 < len(texto) and texto[i + 1].isalpha():
            trocado = texto[:i] + texto[i + 1] + texto[i] + texto[i + 2 :]  # letras invertidas
            if trocado != texto:
                return trocado
        substituta = self._escolher([c for c in "aeiorstnlm" if c != texto[i].lower()])
        return texto[:i] + substituta + texto[i + 1 :]

    def _artefato(self, texto: str) -> str:
        """Espaço inserido no meio de uma palavra, como na extração de texto de PDF."""
        posicoes = [
            i for i in range(1, len(texto) - 1) if texto[i].isalpha() and texto[i - 1].isalpha()
        ]
        i = self._escolher(posicoes)
        return texto[:i] + " " + texto[i:]

    def _variante_local(self, local: str) -> str:
        opcoes = [
            local.upper(),
            sem_acento(local),
            sem_acento(local).upper(),
            local.lower(),
            " ".join(ABREVIACOES.get(p, p) for p in local.split()),
            local.replace(" ", "  ", 1),
            local + " ",
        ]
        return self._escolher([v for v in opcoes if v != local])

    def _bmp_trocado(self, bmp: str) -> str:
        pares = [i for i in range(len(bmp) - 1) if bmp[i] != bmp[i + 1]]
        if pares and self.rng.random() < 0.6:
            i = self._escolher(pares)  # dois dígitos vizinhos invertidos
            return bmp[:i] + bmp[i + 1] + bmp[i] + bmp[i + 2 :]
        i = int(self.rng.integers(0, len(bmp)))
        digito = self._escolher([d for d in "0123456789" if d != bmp[i]])
        return bmp[:i] + digito + bmp[i + 1 :]

    # ------------------------------------------------------------ injeção dos erros
    def gerar(self) -> list[Linha]:
        linhas = self.linhas_limpas()
        n = len(linhas)
        taxas = cat.TAXAS_ERRO
        todas = [True] * n

        # P14 legítimo: sem BMP porque ainda aguarda tombamento (não é erro de digitação).
        for linha in linhas:
            if not linha.bmp:
                self._registrar(linha, "P14", "bmp_ausente_legitimo", "bmp", "", "")

        for i in self._sortear(linhas, taxas["nomenclatura_variante"], todas):  # P12
            certo = linhas[i].nomenclatura
            linhas[i].nomenclatura = self._variante_nome(certo)
            self._registrar(
                linhas[i],
                "P12",
                "nomenclatura_variante",
                "nomenclatura",
                linhas[i].nomenclatura,
                self.tipos[linhas[i].material].nome,
            )
        for i in self._sortear(linhas, taxas["digitacao"], todas):  # P13
            antes = linhas[i].nomenclatura
            linhas[i].nomenclatura = self._digitacao(antes)
            self._registrar(
                linhas[i],
                "P13",
                "digitacao",
                "nomenclatura",
                linhas[i].nomenclatura,
                self.tipos[linhas[i].material].nome,
            )
        for i in self._sortear(linhas, taxas["artefato_extracao"], todas):  # P13
            linhas[i].nomenclatura = self._artefato(linhas[i].nomenclatura)
            self._registrar(
                linhas[i],
                "P13",
                "artefato_extracao",
                "nomenclatura",
                linhas[i].nomenclatura,
                self.tipos[linhas[i].material].nome,
            )

        com_bmp = [bool(linha.bmp) for linha in linhas]
        ausentes = self._sortear(linhas, taxas["bmp_ausente_erro"], com_bmp)
        for i in ausentes:  # P14 erro: o BMP existe, mas não foi preenchido
            self._registrar(linhas[i], "P14", "bmp_ausente_erro", "bmp", "", linhas[i].bmp)
            linhas[i].bmp = ""
        elegiveis = [bool(linha.bmp) for linha in linhas]
        for i in self._sortear(linhas, taxas["bmp_digito_trocado"], elegiveis):  # P14
            certo = linhas[i].bmp
            linhas[i].bmp = self._bmp_trocado(certo)
            self._registrar(linhas[i], "P14", "bmp_digito_trocado", "bmp", linhas[i].bmp, certo)

        # P15: número de série de outra unidade do mesmo tipo (elegível só quem tem série e
        # tem ao menos uma "irmã" do mesmo tipo com série de onde copiar).
        series_por_tipo = Counter(linha.material for linha in linhas if linha.numero_serie)
        com_irma = [bool(x.numero_serie) and series_por_tipo[x.material] > 1 for x in linhas]
        for i in self._sortear(linhas, taxas["serie_duplicada"], com_irma):
            mesmas = [
                j
                for j, outra in enumerate(linhas)
                if j != i and outra.material == linhas[i].material and outra.numero_serie
            ]
            certo = linhas[i].numero_serie
            linhas[i].numero_serie = linhas[self._escolher(mesmas)].numero_serie
            self._registrar(
                linhas[i], "P15", "serie_duplicada", "numero_serie", linhas[i].numero_serie, certo
            )

        # P16: local escrito de vários jeitos (só locais físicos, não "Com fulano").
        fisicos = [not linha.local.startswith("Com ") for linha in linhas]
        for i in self._sortear(linhas, taxas["local_variante"], fisicos):
            certo = linhas[i].local
            linhas[i].local = self._variante_local(certo)
            self._registrar(linhas[i], "P16", "local_variante", "local", linhas[i].local, certo)

        # P16: divergências com o histórico, nas unidades cauteladas.
        cauteladas = [i for i, linha in enumerate(linhas) if linha.situacao == "CAUTELADO"]
        ordem = [cauteladas[int(k)] for k in self.rng.permutation(len(cauteladas))]
        qtd_divergencia = min(len(ordem), round(taxas["divergencia_historico"] * n))
        qtd_baixa = min(len(ordem) - qtd_divergencia, round(taxas["baixa_com_detentor"] * n))
        for i in ordem[:qtd_divergencia]:  # planilha diz "no depósito", histórico diz cautelada
            unidade_local = self.tipos[linhas[i].material].local
            self._registrar(
                linhas[i], "P16", "divergencia_historico", "local", unidade_local, linhas[i].local
            )
            linhas[i].local = unidade_local
            linhas[i].situacao = "LOCALIZADO"
        for i in ordem[qtd_divergencia : qtd_divergencia + qtd_baixa]:  # descarga com detentor
            self._registrar(
                linhas[i], "P16", "baixa_com_detentor", "situacao", "DESCARGA", linhas[i].situacao
            )
            linhas[i].situacao = "DESCARGA"

        # P15: linhas repetidas (a mesma linha aparece duas vezes).
        duplicadas = self._sortear(linhas, taxas["linha_duplicada"], todas)
        for i in sorted(duplicadas, reverse=True):
            # A cópia herda os erros da original (tem os mesmos valores) e ganha mais um.
            copia = replace(linhas[i], duplicata_de=i, erros=list(linhas[i].erros))
            self._registrar(copia, "P15", "linha_duplicada", "", "", "")
            linhas.insert(i + 1, copia)
        # duplicata_de passa a apontar para a posição final da original.
        final: list[Linha] = []
        for linha in linhas:
            if linha.duplicata_de is not None:
                linha.duplicata_de = len(final) - 1
            final.append(linha)
        return final


def gerar_planilha(dataset: Dataset) -> list[Linha]:
    return GeradorPlanilha(dataset, dataset.semente).gerar()
