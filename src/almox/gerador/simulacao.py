"""Simulação de 12 meses de uma unidade logística fictícia.

Percorre o período dia a dia e produz os cadastros e a lista de eventos (entradas,
cautelas, devoluções, mudanças de situação, consumo, ajustes e estornos).

Ideia central: um evento pode ser emitido já com o horário (futuro) em que acontece,
desde que o estado de disponibilidade seja atualizado junto. Ao cautelar uma unidade, a
devolução já é sorteada e emitida, e a unidade fica "ocupada até" aquele instante. Uma
unidade comprada em julho existe desde o início, mas fica ocupada até a incorporação.
No fim, os eventos são ordenados por horário.

A simulação respeita as regras que o banco impõe (unidade ocupada não sai, saldo nunca
negativo, pessoa transferida não retira, eventos de cada item em ordem cronológica).
A carga reproduz os eventos pelas funções do banco: se a simulação violasse uma regra,
a carga falharia.

Toda aleatoriedade vem de um único gerador do NumPy com semente fixa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np

from almox.gerador import catalogo as cat

SEMPRE = datetime(9999, 1, 1, tzinfo=cat.FUSO)  # "ocupada até sempre"


# ============================================================ estruturas
@dataclass
class Pessoa:
    matricula: str
    nome: str
    setor: str
    data_entrada: date
    data_saida: date | None
    perfil: str = "pontual"  # P2: pontual, ocasional ou reincidente

    def presente(self, dia: date) -> bool:
        return self.data_entrada <= dia and (self.data_saida is None or dia < self.data_saida)


@dataclass(frozen=True)
class Usuario:
    login: str
    matricula: str
    perfil: str


@dataclass
class Unidade:
    ref: str
    codigo: str
    bmp: str | None
    serie: str | None
    local: str
    peso: float  # preferência de uso; peso 0 = nunca circula
    ocupada_ate: datetime  # indisponível para cautela antes deste instante


@dataclass
class Evento:
    ocorrida_em: datetime
    operacao: str
    usuario: str
    material: str
    unidade: str | None = None
    pessoa: str | None = None
    quantidade: int | None = None
    estado: str | None = None
    novo_status: str | None = None
    bmp: str | None = None
    numero_serie: str | None = None
    local: str | None = None
    setor_destino: str | None = None
    documento: str | None = None
    observacao: str | None = None
    estorno_de: int | None = None
    seq: int = 0  # identificador do evento (ordem de criação)


@dataclass(frozen=True)
class PedidoCompra:
    feito_em: date
    chegada: date
    quantidade: int


@dataclass
class Saldo:
    codigo: str
    local: str
    minimo: int
    maximo: int
    quantidade: int
    pendentes: list[PedidoCompra] = field(default_factory=list)


@dataclass
class Dataset:
    inicio: date
    fim: date
    semente: int
    pessoas: list[Pessoa]
    usuarios: list[Usuario]
    unidades: list[Unidade]
    saldos: list[Saldo]
    eventos: list[Evento]  # em ordem cronológica
    # Verdade conhecida só pelo gerador: serve aos testes dos padrões e para conferir as
    # análises no fim. As análises não usam isto para chegar às conclusões.
    demanda_nao_atendida: list[tuple[date, str, int]]
    dias_de_pico: list[date]


# ============================================================ simulação
class Simulacao:
    def __init__(self, semente: int, ancora: date) -> None:
        self.rng = np.random.default_rng(semente)
        self.semente = semente
        self.fim = ancora
        self.inicio = inicio_do_periodo(ancora)
        self.limite = datetime.combine(ancora, time(23, 59, 59), tzinfo=cat.FUSO)
        self.tipos = {t.codigo: t for t in cat.SERIAIS}
        self.eventos: list[Evento] = []
        self.pessoas: list[Pessoa] = []
        self.usuarios: list[Usuario] = []
        self.unidades: list[Unidade] = []
        self.saldos: dict[str, Saldo] = {}
        self.nao_atendida: list[tuple[date, str, int]] = []
        self.dias_de_pico: list[date] = []
        self.com_radio_ate: dict[str, datetime] = {}  # matrícula -> devolução do rádio
        self._bmps: set[str] = set()
        self._notas = 0
        dias_uteis = [d for d in self._dias() if self._util(d)]
        self.dias_estorno_serial = set(self._sortear_dias(dias_uteis, cat.ESTORNOS_SERIAL))
        self.dias_estorno_consumo = set(self._sortear_dias(dias_uteis, cat.ESTORNOS_CONSUMO))

    # ------------------------------------------------------------ utilidades
    def _dias(self) -> list[date]:
        return [self.inicio + timedelta(days=i) for i in range((self.fim - self.inicio).days + 1)]

    @staticmethod
    def _util(dia: date) -> bool:
        return dia.weekday() < 5

    def _dia_do_periodo(self, deslocamento: int) -> date | None:
        """Dia útil `deslocamento` dias após o início (fim de semana passa para segunda).
        None se cair depois do fim do período: o acontecimento não entra neste ano."""
        dia = self.inicio + timedelta(days=deslocamento)
        while not self._util(dia):
            dia += timedelta(days=1)
        return dia if dia <= self.fim else None

    def _sortear_dias(self, dias: list[date], quantidade: int) -> list[date]:
        indices = sorted(self.rng.choice(len(dias), quantidade, replace=False))
        return [dias[int(i)] for i in indices]

    def _instante(self, dia: date, hora: float) -> datetime:
        """Dia + hora decimal (7.5 = 07:30), com segundos aleatórios para evitar empates."""
        segundos = int(hora * 3600) + int(self.rng.integers(0, 60))
        return datetime.combine(dia, time(0), tzinfo=cat.FUSO) + timedelta(seconds=segundos)

    def _uniforme(self, a: float, b: float) -> float:
        return float(self.rng.uniform(a, b))

    def _inteiro(self, a: int, b: int) -> int:
        """Inteiro entre a e b, inclusive."""
        return int(self.rng.integers(a, b + 1))

    def _escolher[T](self, itens: list[T], pesos: list[float] | None = None) -> T:
        if pesos is None:
            return itens[int(self.rng.integers(0, len(itens)))]
        total = sum(pesos)
        return itens[int(self.rng.choice(len(itens), p=[p / total for p in pesos]))]

    def _emitir(self, evento: Evento) -> Evento:
        evento.seq = len(self.eventos) + 1
        self.eventos.append(evento)
        return evento

    # ------------------------------------------------------------ quem executa
    def _equipe(self, perfil: str) -> list[Usuario]:
        return [u for u in self.usuarios if u.perfil == perfil]

    def _equipamentista(self, instante: datetime) -> str:
        """Serviço de 24 h (07:00 às 07:00), em rodízio entre os equipamentistas."""
        equipe = self._equipe("EQUIPAMENTISTA")
        dia_de_servico = (instante - timedelta(hours=7)).date()
        return equipe[dia_de_servico.toordinal() % len(equipe)].login

    def _estoquista(self, instante: datetime) -> str:
        """Estoquista no expediente (dias úteis, 08h-17h); fora dele, o equipamentista."""
        if self._util(instante.date()) and 8 <= instante.hour < 17:
            equipe = self._equipe("ESTOQUISTA")
            return equipe[instante.isocalendar().week % len(equipe)].login
        return self._equipamentista(instante)

    def _administrador(self) -> str:
        return self._equipe("ADMINISTRADOR")[0].login

    # ------------------------------------------------------------ pessoas
    def criar_pessoas(self) -> None:
        pares = [f"{n} {s}" for n in cat.NOMES for s in cat.SOBRENOMES]
        nomes = [pares[int(i)] for i in self.rng.permutation(len(pares))]
        matriculas = [str(m) for m in self.rng.choice(4_000_000, 60, replace=False) + 3_000_000]
        for setor, quantidade in cat.PESSOAS_POR_SETOR.items():
            for _ in range(quantidade):
                entrada = date(
                    self._inteiro(2015, 2024), self._inteiro(1, 12), self._inteiro(1, 28)
                )
                self.pessoas.append(Pessoa(matriculas.pop(), nomes.pop(), setor, entrada, None))

        # Usuários do sistema: pessoas presentes desde antes do período.
        for i, (perfil, setor) in enumerate(cat.USUARIOS):
            livres = [
                p
                for p in self.pessoas
                if p.setor == setor and p.matricula not in {u.matricula for u in self.usuarios}
            ]
            pessoa = self._escolher(livres)
            primeiro = pessoa.nome.split()[0].lower().translate(_SEM_ACENTO)
            self.usuarios.append(Usuario(f"{primeiro}.{i + 1:02d}", pessoa.matricula, perfil))

        usuarios = {u.matricula for u in self.usuarios}
        comuns = [p for p in self.pessoas if p.matricula not in usuarios]

        # Chegadas durante o período.
        chegam = [comuns[int(i)] for i in self.rng.choice(len(comuns), 4, replace=False)]
        for pessoa, deslocamento in zip(chegam, cat.CHEGADAS_NO_PERIODO, strict=True):
            chegada = self._dia_do_periodo(deslocamento)
            if chegada is not None:
                pessoa.data_entrada = chegada

        # P2: 4 reincidentes entre quem usa rádio todo dia (SEG/OPER); 8 ocasionais.
        antigos = [p for p in comuns if p not in chegam]
        de_radio = [p for p in antigos if p.setor in ("SEG", "OPER")]
        for i in self.rng.choice(len(de_radio), cat.QTD_PERFIS["reincidente"], replace=False):
            de_radio[int(i)].perfil = "reincidente"
        pontuais = [p for p in self.pessoas if p.perfil == "pontual"]
        for i in self.rng.choice(len(pontuais), cat.QTD_PERFIS["ocasional"], replace=False):
            pontuais[int(i)].perfil = "ocasional"

    def _presentes(self, dia: date, setores: tuple[str, ...]) -> list[Pessoa]:
        return [p for p in self.pessoas if p.setor in setores and p.presente(dia)]

    # ------------------------------------------------------------ carga patrimonial
    def _bmps_consecutivos(self, quantidade: int) -> list[str]:
        """Um lote recebe números consecutivos, como numa incorporação real."""
        while True:
            base = self._inteiro(5_000_000, 5_980_000)
            lote = [str(base + i) for i in range(quantidade)]
            if not self._bmps.intersection(lote):
                self._bmps.update(lote)
                return lote

    def _serie(self, tipo: cat.TipoSerial, ano: int) -> str | None:
        if tipo.serie is None:
            return None
        return f"{tipo.serie}-{ano % 100:02d}-{self._inteiro(0, 99999):05d}"

    def _pesos_de_uso(self, tipo: cat.TipoSerial, quantidade: int) -> list[float]:
        pesos = [float(self.rng.lognormal(0, 0.8)) for _ in range(quantidade)]
        if tipo.uso == "turno":  # parte dos rádios fica guardada como reserva
            pesos = [0.0 if self.rng.random() < 0.2 else p for p in pesos]
        return pesos

    def incorporar(
        self, tipo: cat.TipoSerial, quantidade: int, dia: date, com_bmp: bool
    ) -> list[Unidade]:
        """Emite a ENTRADA de um lote. Sem BMP, as unidades aguardam tombamento."""
        bmps: list[str | None] = (
            [*self._bmps_consecutivos(quantidade)] if com_bmp else [None] * quantidade
        )
        pesos = self._pesos_de_uso(tipo, quantidade)
        instante = self._instante(dia, 10)
        documento = f"NF-{dia.year}-{self._inteiro(1000, 9999)}"
        lote = []
        for bmp, peso in zip(bmps, pesos, strict=True):
            unidade = Unidade(
                ref=f"U{len(self.unidades) + 1:04d}",
                codigo=tipo.codigo,
                bmp=bmp,
                serie=self._serie(tipo, dia.year),
                local=tipo.local,
                peso=peso,
                ocupada_ate=instante if com_bmp else SEMPRE,
            )
            self.unidades.append(unidade)
            lote.append(unidade)
            self._emitir(
                Evento(
                    instante,
                    "entrada_unidade",
                    self._estoquista(instante),
                    tipo.codigo,
                    unidade=unidade.ref,
                    bmp=bmp,
                    numero_serie=unidade.serie,
                    local=unidade.local,
                    documento=documento,
                )
            )
            instante += timedelta(seconds=30)
        return lote

    def carga_inicial(self) -> None:
        """Unidades incorporadas antes do período, em lotes ao longo dos anos."""
        for tipo in cat.SERIAIS:
            restante = tipo.unidades
            while restante > 0:
                tamanho = min(restante, self._inteiro(1, max(1, tipo.unidades // 2)))
                ano = self._inteiro(*tipo.ano_aquisicao)
                dia = min(
                    date(ano, self._inteiro(1, 12), self._inteiro(1, 28)),
                    self.inicio - timedelta(days=1),
                )
                while not self._util(dia):
                    dia -= timedelta(days=1)
                self.incorporar(tipo, tamanho, dia, com_bmp=True)
                restante -= tamanho
            if tipo.unidades_usadas is not None:  # P6: só as primeiras unidades circulam
                do_tipo = [u for u in self.unidades if u.codigo == tipo.codigo]
                for unidade in do_tipo[tipo.unidades_usadas :]:
                    unidade.peso = 0.0

    def aquisicoes_do_periodo(self) -> None:
        """Compras no período; parte chega sem BMP e só depois é tombada."""
        sem_bmp: list[Unidade] = []
        for deslocamento, codigo, quantidade, com_bmp in cat.AQUISICOES:
            dia = self._dia_do_periodo(deslocamento)
            if dia is None:
                continue
            lote = self.incorporar(self.tipos[codigo], quantidade, dia, com_bmp)
            if not com_bmp:
                sem_bmp += lote
        deslocamento, quantidade = cat.TOMBAMENTO
        dia_tombamento = self._dia_do_periodo(deslocamento)
        if dia_tombamento is None:
            return  # as unidades sem BMP continuam aguardando na data-âncora
        instante = self._instante(dia_tombamento, 14)
        for unidade in sem_bmp[:quantidade]:
            (unidade.bmp,) = self._bmps_consecutivos(1)
            unidade.ocupada_ate = instante
            self._mudar_status(
                unidade,
                "DISPONIVEL",
                instante,
                "Tombamento: número de patrimônio atribuído",
                bmp=unidade.bmp,
            )
            instante += timedelta(seconds=40)

    def patrimonio_fixo(self) -> None:
        """Baixas de móveis ao longo do ano e itens não encontrados no inventário anual."""
        para_baixa: list[Unidade] = []
        for codigo, quantidade in cat.FIXOS_PARA_BAIXA:
            do_tipo = [u for u in self.unidades if u.codigo == codigo]
            para_baixa += [
                do_tipo[int(i)] for i in self.rng.choice(len(do_tipo), quantidade, replace=False)
            ]
        for i, unidade in enumerate(para_baixa):
            dia = self._dia_do_periodo(self._inteiro(30, 250))
            if dia is None:
                continue
            instante = self._instante(dia, 14)
            self._mudar_status(unidade, "BAIXA_PENDENTE", instante, "Item danificado sem conserto")
            if i < cat.FIXOS_BAIXADOS:
                self._baixar_depois(unidade, instante)
        dia_inventario = self._dia_do_periodo(cat.INVENTARIO_ANUAL)
        if dia_inventario is None:
            return
        inventario = self._instante(dia_inventario, 11)
        for codigo, quantidade in cat.FIXOS_NAO_ENCONTRADOS:
            livres = [u for u in self.unidades if u.codigo == codigo and u not in para_baixa]
            for unidade in livres[:quantidade]:
                self._mudar_status(
                    unidade, "NAO_LOCALIZADA", inventario, "Inventário anual: não localizado"
                )

    # ------------------------------------------------------------ situação
    def _mudar_status(
        self,
        unidade: Unidade,
        novo: str,
        instante: datetime,
        justificativa: str,
        executor: str | None = None,
        bmp: str | None = None,
    ) -> None:
        if novo == "BAIXADA":
            executor = self._administrador()  # baixa definitiva é do administrador
        self._emitir(
            Evento(
                instante,
                "alterar_status",
                executor or self._estoquista(instante),
                unidade.codigo,
                unidade=unidade.ref,
                novo_status=novo,
                observacao=justificativa,
                bmp=bmp,
            )
        )

    def _baixar_depois(self, unidade: Unidade, desde: datetime) -> None:
        """Baixa definitiva 20 a 60 dias depois (se ainda couber no período)."""
        dia = desde.date() + timedelta(days=self._inteiro(20, 60))
        while not self._util(dia):
            dia += timedelta(days=1)
        instante = self._instante(dia, 11)
        if instante <= self.limite:
            self._mudar_status(
                unidade, "BAIXADA", instante, "Baixa aprovada em processo de descarga"
            )

    # ------------------------------------------------------------ cautela
    def _prob_atraso(self, pessoa: Pessoa, tipo: cat.TipoSerial) -> float:
        probabilidade = cat.PERFIS[pessoa.perfil]  # P2
        if tipo.eletrica and pessoa.setor == "MANUT":  # P3
            probabilidade = max(probabilidade, cat.PROB_ATRASO_ELETRICA_MANUT)
        return probabilidade

    def _em_horario_de_atendimento(self, instante: datetime) -> datetime:
        """Devoluções acontecem entre 07h e 22h."""
        if instante.hour >= 22:
            return self._instante(instante.date() + timedelta(days=1), self._uniforme(7, 9))
        if instante.hour < 7:
            return self._instante(instante.date(), self._uniforme(7, 9))
        return instante

    def _sortear_devolucao(self, tipo: cat.TipoSerial, pessoa: Pessoa, saida: datetime) -> datetime:
        if tipo.prazo_h is None:
            raise ValueError(f"{tipo.codigo} não é cautelável: não há devolução a sortear")
        prazo = saida + timedelta(hours=tipo.prazo_h)
        atrasa = self.rng.random() < self._prob_atraso(pessoa, tipo)
        if tipo.uso == "turno":  # P1
            if not atrasa:
                return saida + timedelta(hours=self._uniforme(10.5, 11.9))
            dias = 1 if self.rng.random() < 0.55 else self._inteiro(2, 5)
            return self._instante(saida.date() + timedelta(days=dias), self._uniforme(8, 18))
        if not atrasa:
            horas = min(self._uniforme(*tipo.duracao_h), tipo.prazo_h * 0.95)
            devolucao = self._em_horario_de_atendimento(saida + timedelta(hours=horas))
            return min(devolucao, prazo - timedelta(minutes=5))
        if tipo.eletrica and pessoa.setor == "MANUT":
            dias_extras = self._uniforme(5, 30)
        else:
            dias_extras = float(self.rng.lognormal(math.log(3), 0.7))
        return self._em_horario_de_atendimento(prazo + timedelta(days=dias_extras))

    def _livres(self, codigo: str, instante: datetime) -> list[Unidade]:
        return [
            u
            for u in self.unidades
            if u.codigo == codigo and u.peso > 0 and u.ocupada_ate <= instante
        ]

    def cautelar(
        self,
        tipo: cat.TipoSerial,
        pessoa: Pessoa,
        saida: datetime,
        devolucao: datetime | None = None,
        sem_devolucao: bool = False,
    ) -> Unidade | None:
        """Cautela uma unidade livre e emite a devolução (se couber no período).

        Devolve a unidade, ou None se não havia unidade livre (demanda não atendida).
        """
        livres = self._livres(tipo.codigo, saida)
        if not livres:
            return None
        unidade = self._escolher(livres, [u.peso for u in livres])
        radio = tipo.uso == "turno"
        executor = self._equipamentista(saida) if radio else self._estoquista(saida)

        retirada = self._emitir(
            Evento(
                saida,
                "retirada_unidade",
                executor,
                tipo.codigo,
                unidade=unidade.ref,
                pessoa=pessoa.matricula,
                setor_destino=pessoa.setor,
            )
        )
        if radio and saida.date() in self.dias_estorno_serial:
            saida = self._corrigir_pessoa_errada(retirada, pessoa, executor, saida)

        if sem_devolucao:
            unidade.ocupada_ate = SEMPRE
            return unidade
        devolucao = max(
            devolucao or self._sortear_devolucao(tipo, pessoa, saida),
            saida + timedelta(minutes=10),
        )
        unidade.ocupada_ate = devolucao
        if radio:
            self.com_radio_ate[pessoa.matricula] = devolucao
        if devolucao <= self.limite:  # senão, continua cautelada na data-âncora
            self._devolver(tipo, unidade, pessoa, devolucao)
        return unidade

    def _corrigir_pessoa_errada(
        self, retirada: Evento, certa: Pessoa, executor: str, saida: datetime
    ) -> datetime:
        """Cautela lançada na pessoa errada: estorno e novo lançamento (uma vez no dia)."""
        self.dias_estorno_serial.discard(saida.date())
        outras = [p for p in self._presentes(saida.date(), (certa.setor,)) if p is not certa]
        if not outras:
            return saida
        retirada.pessoa = self._escolher(outras).matricula
        self._emitir(
            Evento(
                saida + timedelta(minutes=3),
                "estorno",
                self._administrador(),
                retirada.material,
                unidade=retirada.unidade,
                estorno_de=retirada.seq,
                observacao="Cautela lançada na pessoa errada",
            )
        )
        nova = saida + timedelta(minutes=6)
        self._emitir(
            Evento(
                nova,
                "retirada_unidade",
                executor,
                retirada.material,
                unidade=retirada.unidade,
                pessoa=certa.matricula,
                setor_destino=certa.setor,
            )
        )
        return nova

    def _devolver(
        self, tipo: cat.TipoSerial, unidade: Unidade, pessoa: Pessoa, instante: datetime
    ) -> None:
        chave = "turno" if tipo.uso == "turno" else "outros"
        sorteio = self.rng.random()
        if sorteio < cat.PROB_INSERVIVEL[chave]:
            estado = "INSERVIVEL"
        elif sorteio < cat.PROB_INSERVIVEL[chave] + cat.PROB_AVARIA[chave]:
            estado = "AVARIADO"
        else:
            estado = "BOM"
        executor = (
            self._equipamentista(instante) if tipo.uso == "turno" else self._estoquista(instante)
        )
        self._emitir(
            Evento(
                instante,
                "devolucao_unidade",
                executor,
                tipo.codigo,
                unidade=unidade.ref,
                pessoa=pessoa.matricula,
                estado=estado,
                observacao=None if estado == "BOM" else self._escolher(cat.OBSERVACOES_AVARIA),
            )
        )
        if estado == "INSERVIVEL":
            unidade.ocupada_ate = SEMPRE
            self._baixar_depois(unidade, instante)
        elif estado == "AVARIADO":
            # O retorno da manutenção é lançado pelo estoquista: próximo dia útil, 10h.
            dia = instante.date() + timedelta(days=self._inteiro(5, 25))
            while not self._util(dia):
                dia += timedelta(days=1)
            conserto = self._instante(dia, 10)
            vira_baixa = self.rng.random() < cat.PROB_MANUTENCAO_VIRA_BAIXA
            unidade.ocupada_ate = SEMPRE if vira_baixa else conserto
            if conserto <= self.limite:
                if vira_baixa:
                    self._mudar_status(
                        unidade, "BAIXA_PENDENTE", conserto, "Laudo da manutenção: sem conserto"
                    )
                    self._baixar_depois(unidade, conserto)
                else:
                    self._mudar_status(unidade, "DISPONIVEL", conserto, "Conserto concluído")

    # ------------------------------------------------------------ atividades do dia
    def radios(self, dia: date) -> None:
        """P1: rádios retirados no início do turno por quem está de serviço."""
        media = cat.RADIOS_POR_DIA_UTIL if self._util(dia) else cat.RADIOS_POR_DIA_FIM_DE_SEMANA
        abertura = self._instante(dia, 6.6)
        pessoas = [
            p
            for p in self._presentes(dia, ("SEG", "OPER"))
            if self.com_radio_ate.get(p.matricula, abertura) <= abertura
        ]
        ordem = self.rng.permutation(len(pessoas))
        radios = [self.tipos["RAD-0001"], self.tipos["RAD-0002"]]
        for i in ordem[: int(self.rng.poisson(media))]:
            saida = self._instante(dia, self._uniforme(6.7, 7.3))
            preferido = self._escolher(radios, [0.55, 0.45])
            outro = radios[1] if preferido is radios[0] else radios[0]
            pessoa = pessoas[int(i)]
            if self.cautelar(preferido, pessoa, saida) is None:
                self.cautelar(outro, pessoa, saida)

    def eventuais(self, dia: date) -> None:
        pedidos: list[tuple[datetime, cat.TipoSerial]] = []
        for tipo in cat.SERIAIS:
            if tipo.uso != "eventual" or not (self._util(dia) or tipo.fim_de_semana):
                continue
            taxa = tipo.taxa_dia
            if tipo.eletrica:  # P8
                taxa *= cat.SAZONALIDADE_ELETRICAS.get(dia.month, 1.0)
            faixa = (8.0, 16.0) if self._util(dia) else (7.0, 19.0)
            for _ in range(int(self.rng.poisson(taxa))):
                pedidos.append((self._instante(dia, self._uniforme(*faixa)), tipo))
        for instante, tipo in sorted(pedidos, key=lambda p: (p[0], p[1].codigo)):
            candidatas = self._presentes(dia, tipo.setores)
            if not candidatas:
                continue
            pesos = [float(tipo.setores.count(p.setor)) for p in candidatas]
            if self.cautelar(tipo, self._escolher(candidatas, pesos), instante) is None:
                self.nao_atendida.append((dia, tipo.codigo, 1))

    def solenidade(self, dia: date) -> None:
        """P7: pedidos acima do número de megafones e escadas."""
        if dia not in self.dias_de_pico:
            return
        for codigo in ("SIN-0004", "APO-0001"):
            tipo = self.tipos[codigo]
            for _ in range(tipo.unidades + self._inteiro(1, 2)):
                saida = self._instante(dia, self._uniforme(7.5, 8.5))
                devolucao = self._instante(dia, self._uniforme(17, 18))
                pessoa = self._escolher(self._presentes(dia, tipo.setores))
                if self.cautelar(tipo, pessoa, saida, devolucao=devolucao) is None:
                    self.nao_atendida.append((dia, codigo, 1))

    def transferencias(self, dia: date) -> None:
        """P4: saem da unidade levando material cautelado, que o inventário não localiza.

        Só acontece se o inventário anual couber no período (senão a cautela ficaria
        aberta sem nunca ser conferida, o que não é o padrão P4)."""
        dia_inventario = self._dia_do_periodo(cat.INVENTARIO_ANUAL)
        if dia_inventario is None:
            return
        inventario = self._instante(dia_inventario, 10)
        for codigo, deslocamento in cat.TRANSFERIDOS_COM_MATERIAL:
            if self._dia_do_periodo(deslocamento) != dia:
                continue
            tipo = self.tipos[codigo]
            usuarios = {u.matricula for u in self.usuarios}
            candidatas = [
                p
                for p in self._presentes(dia, tipo.setores)
                if p.perfil == "pontual" and p.data_saida is None and p.matricula not in usuarios
            ]
            pessoa = self._escolher(candidatas)
            unidade = self.cautelar(tipo, pessoa, self._instante(dia, 9), sem_devolucao=True)
            if unidade is None:
                raise RuntimeError(f"P4: nenhuma unidade livre de {codigo} em {dia}")
            pessoa.data_saida = dia + timedelta(days=self._inteiro(3, 15))
            self._mudar_status(
                unidade,
                "NAO_LOCALIZADA",
                inventario,
                "Inventário anual: não localizada; estava cautelada a militar já transferido",
            )
        if dia == self._dia_do_periodo(cat.TRANSFERENCIA_SEM_PENDENCIA):
            usuarios = {u.matricula for u in self.usuarios}
            candidatas = [
                p
                for p in self._presentes(dia, ("SEG", "OPER"))
                if p.perfil == "pontual" and p.data_saida is None and p.matricula not in usuarios
            ]
            self._escolher(candidatas).data_saida = dia

    # ------------------------------------------------------------ consumo
    def _minimo_maximo(self, item: cat.TipoConsumo) -> tuple[int, int]:
        """Mínimo e máximo cadastrados.

        Bem calibrado: ponto de reposição = demanda média no prazo + estoque de segurança,
            minimo = d*L + z * raiz(L * var_d + d^2 * var_L)
        (d, var_d: média e variância da demanda diária; L, var_L: média e variância do
        prazo do fornecedor), usando a demanda do mês de pico (sazonalidade).
        Mal calibrado (P10): mínimo bem abaixo da demanda durante o prazo.
        """
        media = (item.tamanho[0] + item.tamanho[1]) / 2
        variancia = ((item.tamanho[1] - item.tamanho[0] + 1) ** 2 - 1) / 12
        pico = max(cat.SAZONALIDADE.get(item.sazonal or "", {}).values(), default=1.0)
        # Demanda por dia corrido (pedidos só em dias úteis): média e desvio (Poisson composta).
        d = item.pedidos_dia * media * 5 / 7
        variancia_d = item.pedidos_dia * (variancia + media**2) * 5 / 7
        prazo = cat.PRAZO_REPOSICAO_PLANEJADO
        if item.calibracao == "mal_calibrado":  # P10
            minimo = item.minimo_fixo or max(2, round(0.4 * d * prazo))
            return minimo, minimo + max(5, round(d * cat.DIAS_COBERTURA_MAL_CALIBRADO))
        d_pico, var_pico = d * pico, variancia_d * pico
        a, b = cat.PRAZO_REPOSICAO["normal"]
        var_prazo = ((b - a + 1) ** 2 - 1) / 12  # variância do prazo uniforme discreto
        seguranca = cat.Z_SERVICO * math.sqrt(prazo * var_pico + d_pico**2 * var_prazo)
        minimo = math.ceil(d_pico * prazo + seguranca)
        return minimo, minimo + max(5, round(d * cat.DIAS_COBERTURA_MAXIMO))

    def cadastrar_saldos(self) -> None:
        """Saldo inicial de cada material de consumo, lançado como ENTRADA."""
        instante = self._instante(self.inicio, 7)
        estoquista = self._equipe("ESTOQUISTA")[0].login
        for item in cat.CONSUMOS:
            minimo, maximo = self._minimo_maximo(item)
            if item.calibracao == "excesso":  # P9: compra exagerada, acima do máximo o ano todo
                media = (item.tamanho[0] + item.tamanho[1]) / 2
                demanda_anual = item.pedidos_dia * media * 5 / 7 * 365
                inicial = maximo + math.ceil(demanda_anual * cat.ANOS_DE_DEMANDA_NO_EXCESSO)
            else:
                inicial = self._inteiro(minimo + (maximo - minimo) // 3, maximo)
            self.saldos[item.codigo] = Saldo(
                item.codigo, "Almoxarifado de Consumo", minimo, maximo, inicial
            )
            self._emitir(
                Evento(
                    instante,
                    "entrada_consumo",
                    estoquista,
                    item.codigo,
                    quantidade=inicial,
                    documento="SALDO-INICIAL",
                )
            )
            instante += timedelta(seconds=20)

    def consumo(self, dia: date) -> None:
        if not self._util(dia):
            return  # P8: o almoxarifado de consumo não atende no fim de semana
        self._receber_compras(dia)
        pedidos: list[tuple[datetime, cat.TipoConsumo]] = []
        for item in cat.CONSUMOS:
            fator = cat.SAZONALIDADE.get(item.sazonal or "", {}).get(dia.month, 1.0)  # P8
            for _ in range(int(self.rng.poisson(item.pedidos_dia * fator))):
                pedidos.append((self._instante(dia, self._uniforme(10, 16)), item))
        corrigir_hoje = dia in self.dias_estorno_consumo
        for instante, item in sorted(pedidos, key=lambda p: (p[0], p[1].codigo)):
            corrigir_hoje = self._atender(dia, instante, item, corrigir_hoje) and corrigir_hoje
        if dia in {self._dia_do_periodo(d) for d in cat.INVENTARIOS_CONSUMO}:
            self._inventario(dia)
        self._pedir_compras(dia)

    def _receber_compras(self, dia: date) -> None:
        for saldo in self.saldos.values():
            chegando = [p for p in saldo.pendentes if p.chegada == dia]
            saldo.pendentes = [p for p in saldo.pendentes if p.chegada != dia]
            for pedido in chegando:
                instante = self._instante(dia, self._uniforme(9, 9.9))
                saldo.quantidade += pedido.quantidade
                self._notas += 1
                # A data do pedido vai na observação (como numa nota de empenho): é o que
                # permite à análise medir o prazo de entrega de cada fornecimento (P11).
                self._emitir(
                    Evento(
                        instante,
                        "entrada_consumo",
                        self._estoquista(instante),
                        saldo.codigo,
                        quantidade=pedido.quantidade,
                        documento=f"NE-{dia.year}-{self._notas:04d}",
                        observacao=f"Pedido feito em {pedido.feito_em.isoformat()}",
                    )
                )

    def _atender(
        self, dia: date, instante: datetime, item: cat.TipoConsumo, corrigir: bool
    ) -> bool:
        """Atende um pedido (parcialmente, se faltar). Devolve True se a correção por
        estorno ainda está pendente para o dia."""
        saldo = self.saldos[item.codigo]
        pedido = self._inteiro(*item.tamanho)
        candidatas = self._presentes(dia, item.setores)
        if not candidatas:
            return corrigir
        pessoa = self._escolher(candidatas)
        atendido = min(pedido, saldo.quantidade)
        if atendido < pedido:
            self.nao_atendida.append((dia, item.codigo, pedido - atendido))
        if atendido == 0:
            return corrigir
        executor = self._estoquista(instante)

        def retirada(momento: datetime, quantidade: int, obs: str | None) -> Evento:
            return self._emitir(
                Evento(
                    momento,
                    "retirada_consumo",
                    executor,
                    item.codigo,
                    pessoa=pessoa.matricula,
                    quantidade=quantidade,
                    setor_destino=pessoa.setor,
                    observacao=obs,
                )
            )

        parcial = None if atendido == pedido else f"Atendimento parcial: pedido de {pedido}"
        if corrigir and saldo.quantidade > atendido:  # quantidade digitada errada
            errada = retirada(instante, min(saldo.quantidade, atendido + self._inteiro(1, 3)), None)
            self._emitir(
                Evento(
                    instante + timedelta(minutes=3),
                    "estorno",
                    self._administrador(),
                    item.codigo,
                    estorno_de=errada.seq,
                    observacao="Quantidade digitada errada",
                )
            )
            retirada(instante + timedelta(minutes=6), atendido, parcial)
            saldo.quantidade -= atendido
            return False
        retirada(instante, atendido, parcial)
        saldo.quantidade -= atendido
        return corrigir

    def _inventario(self, dia: date) -> None:
        """Inventário trimestral: ajusta o saldo pela contagem quando há diferença."""
        for saldo in self.saldos.values():
            if self.rng.random() >= cat.PROB_DIFERENCA_INVENTARIO:
                continue
            perda = self.rng.random() < 0.8
            diferenca = -self._inteiro(1, 3) if perda else self._inteiro(1, 2)
            contada = max(0, saldo.quantidade + diferenca)
            if contada == saldo.quantidade:
                continue
            instante = self._instante(dia, self._uniforme(16, 16.4))
            saldo.quantidade = contada
            self._emitir(
                Evento(
                    instante,
                    "ajuste_consumo",
                    self._estoquista(instante),
                    saldo.codigo,
                    quantidade=contada,
                    observacao="Inventário trimestral: diferença na contagem",
                )
            )

    def _pedir_compras(self, dia: date) -> None:
        """Revisão de fim de dia: pede compra quando a posição chega ao mínimo (P11)."""
        for item in cat.CONSUMOS:
            saldo = self.saldos[item.codigo]
            posicao = saldo.quantidade + sum(p.quantidade for p in saldo.pendentes)
            if posicao > saldo.minimo:
                continue
            chave = "fornecedor_lento" if item.calibracao == "fornecedor_lento" else "normal"
            chegada = dia + timedelta(days=self._inteiro(*cat.PRAZO_REPOSICAO[chave]))
            while not self._util(chegada):
                chegada += timedelta(days=1)
            saldo.pendentes.append(PedidoCompra(dia, chegada, saldo.maximo - posicao))

    # ------------------------------------------------------------ execução
    def executar(self) -> Dataset:
        self.criar_pessoas()
        self.carga_inicial()
        self.aquisicoes_do_periodo()
        self.patrimonio_fixo()
        self.cadastrar_saldos()
        uteis = [d for d in self._dias() if self._util(d)]
        self.dias_de_pico = self._sortear_dias(uteis, cat.DIAS_DE_PICO)
        for dia in self._dias():
            self.transferencias(dia)
            self.radios(dia)
            self.solenidade(dia)
            self.eventuais(dia)
            self.consumo(dia)
        eventos = sorted(self.eventos, key=lambda e: (e.ocorrida_em, e.seq))
        return Dataset(
            inicio=self.inicio,
            fim=self.fim,
            semente=self.semente,
            pessoas=self.pessoas,
            usuarios=self.usuarios,
            unidades=self.unidades,
            saldos=list(self.saldos.values()),
            eventos=eventos,
            demanda_nao_atendida=self.nao_atendida,
            dias_de_pico=self.dias_de_pico,
        )


_SEM_ACENTO = str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")


def inicio_do_periodo(ancora: date) -> date:
    """Primeiro dia do período de 12 meses que termina na âncora.

    29/02 como âncora: o "mesmo dia" do ano anterior não existe; usa-se 28/02.
    """
    try:
        um_ano_antes = ancora.replace(year=ancora.year - 1)
    except ValueError:
        um_ano_antes = ancora.replace(year=ancora.year - 1, day=28)
    return um_ano_antes + timedelta(days=1)


def gerar(semente: int = cat.SEMENTE_PADRAO, ancora: str = cat.ANCORA_PADRAO) -> Dataset:
    return Simulacao(semente, date.fromisoformat(ancora)).executar()
