"""Atividade de setembro de 2026 no banco da APLICAÇÃO (o "sistema vivo").

Os materiais operacionais (almox.complemento) entram em 01/09/2026. Este módulo simula o
mês seguinte de uso, com a rotina de uma unidade pequena:

- serviço de dia (todo dia, 07:30): 4 militares levam rádio, bateria extra, fone, colete
  refletivo e colete balístico; devolvem na troca do dia seguinte, a outro equipamentista;
- treino de controle de distúrbios (terça e quinta, 13:30): 16 militares, volta às 17:30;
  às vezes um escudo ou capacete volta avariado e vai para manutenção;
- desfile de 7 de setembro: o material de formatura sai na sexta (04/09) e volta na terça
  (08/09); três atrasam, e dois militares ainda não devolveram (posse vencida);
- semana de salto (15 a 17/09) e exercício de campanha (21 a 25/09), com avarias,
  um item inservível e duas posses ainda abertas;
- EPI para as tarefas do dia (dias úteis), reposição de pilhas e de luz química, um lote
  novo de colete tático e o retorno da manutenção (o reparo leva de 4 a 8 dias).

Duas etapas separadas: `planejar` é Python puro (semente fixa, sempre o mesmo plano, e
testável sem banco); `executar` passa cada evento pelas funções de regra do banco, as
mesmas que a tela usa. Sem eventos depois de 01/10/2026 (o banco recusa fato do futuro):
o serviço do dia 01/10 fica em posse, como na vida real.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import psycopg

from almox.banco import Conexao, chamar_funcao

FUSO = ZoneInfo("America/Recife")
INICIO = date(2026, 9, 1)
FIM = date(2026, 10, 1)
SEMENTE = 2026
FERIADOS = {date(2026, 9, 7)}

KIT_SERVICO = ("COM-0001", "COM-0002", "COM-0003", "EPP-0006", "BAL-0001")
KIT_CHOQUE = ("CHQ-0001", "CHQ-0002", "CHQ-0003", "CHQ-0004", "CHQ-0005", "CHQ-0006")
KIT_FORMATURA = ("FOR-0001", "FOR-0002", "FOR-0003", "FOR-0004", "FOR-0006")
KIT_SALTO = (
    "PQD-0001", "PQD-0002", "PQD-0003", "PQD-0005", "PQD-0006",
    "PQD-0008", "PQD-0009", "PQD-0010",
)  # fmt: skip
KIT_CAMPANHA = (
    "CPA-0001", "CPA-0002", "CPA-0003", "CPA-0004", "CPA-0005",
    "CPA-0006", "CPA-0011", "CPA-0018",
)  # fmt: skip
EPI_DO_DIA = ("EPP-0001", "EPP-0002", "EPP-0004", "EPP-0005", "EPP-0011")

ESPACO = uuid.UUID("6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f")  # para uuid5 reproduzível


# ------------------------------------------------------------------ eventos do plano
@dataclass(frozen=True)
class Retirada:
    em: datetime
    executor: int
    pessoa: int
    itens: tuple[tuple[str, int], ...]
    operacao: uuid.UUID
    finalidade: str
    estado: str = "BOM"
    observacao: str | None = None


@dataclass(frozen=True)
class Devolucao:
    """Devolve o que ainda estiver em posse da retirada `de`. As avarias escolhem, de cada
    material citado, a unidade de menor id."""

    em: datetime
    executor: int
    de: uuid.UUID
    operacao: uuid.UUID
    avarias: tuple[tuple[str, str, str], ...] = ()  # (código, AVARIADO|INSERVIVEL, obs)


@dataclass(frozen=True)
class RetornoDaManutencao:
    """Unidades em manutenção há pelo menos `dias_minimos` voltam a ficar disponíveis."""

    em: datetime
    executor: int
    dias_minimos: int


@dataclass(frozen=True)
class Baixa:
    """Unidades em baixa pendente há pelo menos 7 dias são baixadas (administrador)."""

    em: datetime
    executor: int


@dataclass(frozen=True)
class EntradaConsumo:
    em: datetime
    executor: int
    codigo: str
    quantidade: int
    documento: str


@dataclass(frozen=True)
class EntradaUnidades:
    em: datetime
    executor: int
    codigo: str
    quantidade: int
    documento: str


Evento = Retirada | Devolucao | RetornoDaManutencao | Baixa | EntradaConsumo | EntradaUnidades


@dataclass(frozen=True)
class Operadores:
    equipamentistas: tuple[int, ...]
    estoquista: int
    administrador: int


@dataclass
class _Planejador:
    pessoas: tuple[int, ...]
    operadores: Operadores
    rng: np.random.Generator
    eventos: list[Evento] = field(default_factory=list)
    _n: int = 0

    def codigo(self) -> uuid.UUID:
        self._n += 1
        return uuid.uuid5(ESPACO, f"atividade-{self._n}")

    def quando(self, dia: date, hora: int, minuto: int, espalhar: int = 0) -> datetime:
        extra = int(self.rng.integers(0, espalhar + 1)) if espalhar else 0
        return datetime.combine(dia, time(hora, minuto), tzinfo=FUSO) + timedelta(minutes=extra)

    def de_servico(self, dia: date) -> int:
        """O equipamentista de serviço no balcão (rodízio diário)."""
        equip = self.operadores.equipamentistas
        return equip[(dia - INICIO).days % len(equip)]

    def sorteio(self, quantos: int) -> list[int]:
        escolhidos = self.rng.choice(len(self.pessoas), size=quantos, replace=False)
        return [self.pessoas[int(i)] for i in escolhidos]

    def retirar(
        self,
        em: datetime,
        executor: int,
        pessoa: int,
        itens: Sequence[tuple[str, int]],
        finalidade: str,
        estado: str = "BOM",
        observacao: str | None = None,
    ) -> uuid.UUID:
        operacao = self.codigo()
        self.eventos.append(
            Retirada(em, executor, pessoa, tuple(itens), operacao, finalidade, estado, observacao)
        )
        return operacao

    def devolver(
        self,
        em: datetime,
        executor: int,
        de: uuid.UUID,
        avarias: Sequence[tuple[str, str, str]] = (),
    ) -> None:
        if em.date() <= FIM:
            self.eventos.append(Devolucao(em, executor, de, self.codigo(), tuple(avarias)))


def _dias() -> list[date]:
    return [INICIO + timedelta(days=i) for i in range((FIM - INICIO).days + 1)]


def _util(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in FERIADOS


def planejar(
    pessoas: Sequence[int], operadores: Operadores, semente: int = SEMENTE
) -> list[Evento]:
    """O plano do mês, em ordem cronológica. Mesmos dados de entrada, mesmo plano."""
    if len(pessoas) < 28:
        raise ValueError(f"a simulação precisa de pelo menos 28 militares (há {len(pessoas)})")
    p = _Planejador(tuple(sorted(pessoas)), operadores, np.random.default_rng(semente))
    _servico_de_dia(p)
    _choque(p)
    _desfile(p)
    _salto(p)
    _campanha(p)
    _epi_do_dia(p)
    _estoque(p)
    # Ordem estável: no mesmo minuto, devolução antes de retirada (a troca do serviço
    # devolve o kit antes de o novo serviço pegar).
    ordem = {Devolucao: 0, RetornoDaManutencao: 1, Baixa: 1, EntradaConsumo: 2,
             EntradaUnidades: 2, Retirada: 3}  # fmt: skip
    return sorted(p.eventos, key=lambda e: (e.em, ordem[type(e)]))


def _servico_de_dia(p: _Planejador) -> None:
    anteriores: list[uuid.UUID] = []
    for dia in _dias():
        executor = p.de_servico(dia)
        # A guarda que sai devolve o kit primeiro; às vezes alguém atrasa e devolve às 10h.
        for operacao in anteriores:
            atraso = float(p.rng.random()) < 0.08
            p.devolver(p.quando(dia, 10 if atraso else 7, 40, 30), executor, operacao)
        anteriores = []
        for pessoa in p.sorteio(4):
            itens = [(codigo, 1) for codigo in KIT_SERVICO]
            if (dia - INICIO).days % 2 == 0:
                itens.append(("PIL-0001", 1))
            anteriores.append(
                p.retirar(p.quando(dia, 7, 30, 20), executor, pessoa, itens, "Serviço de dia")
            )


def _choque(p: _Planejador) -> None:
    for dia in _dias():
        if dia.weekday() not in (1, 3) or not _util(dia):
            continue
        executor = p.de_servico(dia)
        operacoes = []
        for pessoa in p.sorteio(16):
            regular = float(p.rng.random()) < 0.06
            operacoes.append(
                p.retirar(
                    p.quando(dia, 13, 30, 25),
                    executor,
                    pessoa,
                    [(codigo, 1) for codigo in KIT_CHOQUE],
                    "Treino de controle de distúrbios",
                    "REGULAR" if regular else "BOM",
                    "Riscos na viseira e no escudo" if regular else None,
                )
            )
        avariadas = {int(i) for i in p.rng.choice(len(operacoes), size=2, replace=False)}
        for i, operacao in enumerate(operacoes):
            avarias: list[tuple[str, str, str]] = []
            if i in avariadas:
                codigo = ("CHQ-0001", "CHQ-0002")[i % 2]
                avarias.append((codigo, "AVARIADO", "Trincado no treino"))
            p.devolver(p.quando(dia, 17, 30, 40), executor, operacao, avarias)


def _desfile(p: _Planejador) -> None:
    sexta = date(2026, 9, 4)
    terca = date(2026, 9, 8)
    equip = p.operadores.equipamentistas
    tropa = p.sorteio(30)
    operacoes: list[uuid.UUID] = []
    for i, pessoa in enumerate(tropa):
        itens = [(codigo, 1) for codigo in KIT_FORMATURA]
        if i < 2:  # porta-bandeiras
            itens += [("FOR-0007", 1), ("FOR-0008", 1)]
        elif i == 2:
            itens += [("FOR-0009", 1), ("FOR-0011", 1)]
        elif i == 3:
            itens += [("FOR-0010", 1), ("FOR-0011", 1)]
        elif i < 8:  # oficiais da tropa
            itens += [("FOR-0013", 1), ("FOR-0014", 1)]
        elif i < 20:  # os de espadim (há 20)
            itens.append(("FOR-0012", 1))
        operacoes.append(
            p.retirar(
                p.quando(sexta, 14, 0, 90),
                equip[i % 2],
                pessoa,
                itens,
                "Desfile de 7 de Setembro",
            )
        )
    for i, operacao in enumerate(operacoes):
        if i in (5, 17):  # ainda não devolveram
            continue
        if i in (9, 21, 26):  # atrasaram
            dia = date(2026, 9, 10 + i % 2)
            p.devolver(p.quando(dia, 9, 0, 120), p.de_servico(dia), operacao)
            continue
        avarias = [("FOR-0003", "INSERVIVEL", "Luvas rasgadas e manchadas")] if i == 12 else []
        p.devolver(p.quando(terca, 8, 0, 150), equip[(i + 1) % 2], operacao, avarias)


def _salto(p: _Planejador) -> None:
    ida = date(2026, 9, 15)
    volta = date(2026, 9, 17)
    operacoes = []
    for i, pessoa in enumerate(p.sorteio(14)):
        itens = [(codigo, 1) for codigo in KIT_SALTO]
        if i < 10:
            itens.append(("PQD-0004", 1))
        if i < 5:
            itens.append(("PQD-0007", 1))
        operacoes.append(
            p.retirar(p.quando(ida, 6, 0, 40), p.de_servico(ida), pessoa, itens, "Semana de salto")
        )
    for i, operacao in enumerate(operacoes):
        avarias = [("PQD-0002", "AVARIADO", "Velame com furo de 3 cm")] if i == 6 else []
        p.devolver(p.quando(volta, 17, 0, 60), p.de_servico(volta), operacao, avarias)


def _campanha(p: _Planejador) -> None:
    ida = date(2026, 9, 21)
    operacoes = []
    for i, pessoa in enumerate(p.sorteio(22)):
        itens = [(codigo, 1) for codigo in KIT_CAMPANHA]
        itens += [("CPA-0013", 2 if i < 8 else 1), ("LUZ-0001", 2)]
        if i < 4:  # comandantes de fração
            itens += [("CPA-0009", 1), ("CPA-0010", 1), ("COM-0001", 1), ("COM-0009", 1)]
        if i % 5 == 0:
            itens += [("CPA-0014", 1), ("CPA-0012", 1), ("FIT-0001", 1)]
        operacoes.append(
            p.retirar(
                p.quando(ida, 6, 0, 60),
                p.operadores.equipamentistas[i % 2],
                pessoa,
                itens,
                "Exercício de campanha",
            )
        )
    for i, operacao in enumerate(operacoes):
        if i in (3, 14):  # ainda em posse, vencida
            continue
        dia = date(2026, 9, 25) if i < 16 else date(2026, 9, 28)
        avarias: list[tuple[str, str, str]] = []
        if i in (2, 11):
            avarias.append(("CPA-0001", "AVARIADO", "Barraca com a lona rasgada"))
        if i == 8:
            avarias.append(("CPA-0004", "INSERVIVEL", "Cantil amassado e furado"))
        p.devolver(p.quando(dia, 14, 0, 180), p.de_servico(dia), operacao, avarias)


def _epi_do_dia(p: _Planejador) -> None:
    for dia in _dias():
        if not _util(dia):
            continue
        executor = p.de_servico(dia)
        quantos = int(p.rng.integers(2, 5))
        for pessoa in p.sorteio(quantos):
            n = int(p.rng.integers(2, 4))
            escolhidos = p.rng.choice(len(EPI_DO_DIA), size=n, replace=False)
            itens = [(EPI_DO_DIA[int(i)], 1) for i in sorted(escolhidos)]
            operacao = p.retirar(
                p.quando(dia, 8, 0, 60), executor, pessoa, itens, "Manutenção das instalações"
            )
            avarias = []
            if float(p.rng.random()) < 0.05 and any(c == "EPP-0005" for c, _ in itens):
                avarias.append(("EPP-0005", "INSERVIVEL", "Luva furada na palma"))
            p.devolver(p.quando(dia, 16, 0, 60), executor, operacao, avarias)


def _estoque(p: _Planejador) -> None:
    estoquista = p.operadores.estoquista
    for dia in _dias():
        if dia.weekday() in (0, 3) and _util(dia):
            p.eventos.append(RetornoDaManutencao(p.quando(dia, 10, 0), estoquista, 4))
    p.eventos.append(
        EntradaConsumo(p.quando(date(2026, 9, 15), 10, 30), estoquista, "PIL-0001", 120, "NF 4471")
    )
    p.eventos.append(
        EntradaConsumo(p.quando(date(2026, 9, 18), 11, 0), estoquista, "LUZ-0001", 150, "NF 4502")
    )
    p.eventos.append(
        EntradaUnidades(p.quando(date(2026, 9, 18), 11, 30), estoquista, "CPA-0008", 6, "NF 4503")
    )
    p.eventos.append(Baixa(p.quando(date(2026, 9, 30), 16, 0), p.operadores.administrador))


# ------------------------------------------------------------------ execução
@dataclass
class Resumo:
    retiradas: int = 0
    devolucoes: int = 0
    itens_sem_estoque: int = 0
    avarias: int = 0
    retornos_da_manutencao: int = 0
    baixas: int = 0
    entradas: int = 0


def _ids_dos_materiais(con: Conexao) -> dict[str, int]:
    return {codigo: id_ for id_, codigo in con.execute("SELECT id, codigo FROM core.material_tipo")}


def executar(con: Conexao, plano: Sequence[Evento]) -> Resumo:
    """Passa cada evento pelas funções de regra. Um item sem estoque (todas as unidades em
    posse ou em manutenção) é pulado e contado, sem desfazer o resto do atendimento."""
    material = _ids_dos_materiais(con)
    resumo = Resumo()
    for evento in plano:
        if isinstance(evento, Retirada):
            _executar_retirada(con, evento, material, resumo)
        elif isinstance(evento, Devolucao):
            _executar_devolucao(con, evento, material, resumo)
        elif isinstance(evento, RetornoDaManutencao):
            _executar_retorno(con, evento, resumo)
        elif isinstance(evento, Baixa):
            _executar_baixa(con, evento, resumo)
        elif isinstance(evento, EntradaConsumo):
            chamar_funcao(
                con,
                "registrar_entrada_consumo",
                p_material_tipo_id=material[evento.codigo],
                p_quantidade=evento.quantidade,
                p_executado_por=evento.executor,
                p_ocorrida_em=evento.em,
                p_documento_ref=evento.documento,
            )
            resumo.entradas += 1
        else:
            _executar_entrada_de_unidades(con, evento, material, resumo)
    return resumo


def _executar_retirada(
    con: Conexao, evento: Retirada, material: dict[str, int], resumo: Resumo
) -> None:
    for codigo, quantidade in evento.itens:
        try:
            with con.transaction():  # savepoint: um item sem estoque não desfaz os outros
                chamar_funcao(
                    con,
                    "registrar_retirada_lote",
                    p_material_tipo_id=material[codigo],
                    p_quantidade=quantidade,
                    p_pessoa_id=evento.pessoa,
                    p_executado_por=evento.executor,
                    p_operacao=evento.operacao,
                    p_estado_retirada=evento.estado,
                    p_finalidade=evento.finalidade,
                    p_observacao=evento.observacao,
                    p_ocorrida_em=evento.em,
                )
        except psycopg.Error as erro:  # só "estoque insuficiente" é esperado
            if erro.sqlstate != "ALM01":
                raise
            resumo.itens_sem_estoque += 1
    resumo.retiradas += 1


def _executar_devolucao(
    con: Conexao, evento: Devolucao, material: dict[str, int], resumo: Resumo
) -> None:
    linhas = con.execute(
        "SELECT u.id, u.material_tipo_id, u.detentor_id FROM core.movimentacao m "
        "JOIN core.unidade_patrimonial u ON u.id = m.unidade_id "
        "WHERE m.operacao = %s AND m.tipo = 'RETIRADA' AND u.status = 'CAUTELADA' "
        "AND u.detentor_id = m.pessoa_id ORDER BY u.id",
        [evento.de],
    ).fetchall()
    if not linhas:
        return
    pessoa = linhas[0][2]
    por_estado: dict[tuple[str, str | None], list[int]] = {}
    usadas: set[int] = set()
    for codigo, estado_avaria, motivo in evento.avarias:
        unidade = next((u for u, m, _ in linhas if m == material[codigo] and u not in usadas), None)
        if unidade is not None:
            usadas.add(unidade)
            por_estado.setdefault((estado_avaria, motivo), []).append(unidade)
            resumo.avarias += 1
    boas = [u for u, _, _ in linhas if u not in usadas]
    if boas:
        por_estado[("BOM", None)] = boas
    for i, ((estado, observacao), unidades) in enumerate(sorted(por_estado.items())):
        chamar_funcao(
            con,
            "registrar_devolucao_lote",
            p_unidades=unidades,
            p_pessoa_id=pessoa,
            p_executado_por=evento.executor,
            p_estado=estado,
            p_observacao=observacao,
            p_operacao=uuid.uuid5(evento.operacao, str(i)),
            p_ocorrida_em=evento.em,
        )
    resumo.devolucoes += 1


def _executar_retorno(con: Conexao, evento: RetornoDaManutencao, resumo: Resumo) -> None:
    unidades = con.execute(
        "SELECT u.id FROM core.unidade_patrimonial u "
        "JOIN LATERAL (SELECT max(ocorrida_em) AS desde FROM core.movimentacao "
        "              WHERE unidade_id = u.id) m ON true "
        "WHERE u.status = 'EM_MANUTENCAO' AND m.desde <= %s AND u.bmp::integer >= 6100001 "
        "ORDER BY u.id",
        [evento.em - timedelta(days=evento.dias_minimos)],
    ).fetchall()
    for (unidade,) in unidades:
        chamar_funcao(con, "alterar_status_unidade", p_unidade_id=unidade,
                      p_novo_status="DISPONIVEL", p_executado_por=evento.executor,
                      p_justificativa="Reparo concluído", p_ocorrida_em=evento.em)  # fmt: skip
        resumo.retornos_da_manutencao += 1


def _executar_baixa(con: Conexao, evento: Baixa, resumo: Resumo) -> None:
    unidades = con.execute(
        "SELECT u.id FROM core.unidade_patrimonial u "
        "JOIN LATERAL (SELECT max(ocorrida_em) AS desde FROM core.movimentacao "
        "              WHERE unidade_id = u.id) m ON true "
        "WHERE u.status = 'BAIXA_PENDENTE' AND m.desde <= %s AND u.bmp::integer >= 6100001 "
        "ORDER BY u.id",
        [evento.em - timedelta(days=7)],
    ).fetchall()
    for (unidade,) in unidades:
        chamar_funcao(con, "alterar_status_unidade", p_unidade_id=unidade,
                      p_novo_status="BAIXADA", p_executado_por=evento.executor,
                      p_justificativa="Baixa por inservível (laudo do setor)",
                      p_ocorrida_em=evento.em)  # fmt: skip
        resumo.baixas += 1


def _executar_entrada_de_unidades(
    con: Conexao, evento: EntradaUnidades, material: dict[str, int], resumo: Resumo
) -> None:
    proximo = con.execute(
        "SELECT coalesce(max(bmp::integer), 6100000) + 1 FROM core.unidade_patrimonial "
        "WHERE bmp::integer >= 6100001"
    ).fetchone()
    if proximo is None:  # pragma: no cover - SELECT de agregação sempre devolve linha
        raise RuntimeError("sem próximo BMP")
    local = con.execute(
        "SELECT local_id FROM core.unidade_patrimonial WHERE material_tipo_id = %s LIMIT 1",
        [material[evento.codigo]],
    ).fetchone()
    if local is None:
        raise RuntimeError(f"{evento.codigo} não tem unidades para indicar o local")
    for i in range(evento.quantidade):
        chamar_funcao(
            con,
            "registrar_entrada_unidade",
            p_material_tipo_id=material[evento.codigo],
            p_local_id=local[0],
            p_executado_por=evento.executor,
            p_bmp=str(proximo[0] + i),
            p_ocorrida_em=evento.em,
            p_documento_ref=evento.documento,
        )
    resumo.entradas += 1


def pessoas_do_periodo(con: Conexao) -> list[int]:
    """Militares presentes o mês inteiro e sem usuário no sistema (quem opera o balcão
    não atende a si mesmo)."""
    linhas = con.execute(
        "SELECT p.id FROM core.pessoa p "
        "WHERE p.data_entrada <= %s AND (p.data_saida IS NULL OR p.data_saida > %s) "
        "AND NOT EXISTS (SELECT 1 FROM core.usuario u WHERE u.pessoa_id = p.id) "
        "ORDER BY p.matricula",
        [INICIO, FIM],
    ).fetchall()
    return [int(i) for (i,) in linhas]


def operadores(con: Conexao) -> Operadores:
    def ids(perfil: str) -> list[int]:
        return [
            int(i)
            for (i,) in con.execute(
                "SELECT id FROM core.usuario WHERE perfil = %s AND ativo ORDER BY login", [perfil]
            ).fetchall()
        ]

    equipamentistas, estoquistas, administradores = (
        ids("EQUIPAMENTISTA"),
        ids("ESTOQUISTA"),
        ids("ADMINISTRADOR"),
    )
    if len(equipamentistas) < 2 or not estoquistas or not administradores:
        raise ValueError("a simulação precisa de 2 equipamentistas, 1 estoquista e 1 administrador")
    return Operadores(tuple(equipamentistas), estoquistas[0], administradores[0])


def carregar_atividade(con: Conexao) -> Resumo:
    """Planeja e executa o mês, na transação de quem chama (roda como o dono do banco)."""
    plano = planejar(pessoas_do_periodo(con), operadores(con))
    return executar(con, plano)
