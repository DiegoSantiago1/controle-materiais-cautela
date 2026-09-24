"""Testes do gerador: coerência dos dados, padrões P1 a P16 e reprodutibilidade.

Cada padrão prometido no PLAN vira uma asserção. As faixas foram medidas em cinco
sementes (42, 7, 2024, 99, 123) e escolhidas para valer em todas; os testes rodam com
a semente padrão (42), a mesma dos dados carregados no banco.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from almox.gerador import __main__ as cli
from almox.gerador import catalogo as cat
from almox.gerador.planilha import Linha, estado_final, gerar_planilha
from almox.gerador.saida import gravar
from almox.gerador.simulacao import Dataset, gerar

from .padroes import TIPOS, cautelas, cautelas_por_tipo, rupturas_por_material, saldo_diario, taxa

CALIBRACAO = {c.codigo: c.calibracao for c in cat.CONSUMOS}


@pytest.fixture(scope="module")
def dados() -> Dataset:
    return gerar()


@pytest.fixture(scope="module")
def planilha(dados: Dataset) -> list[Linha]:
    return gerar_planilha(dados)


# ================================================================== coerência
def test_volumes_do_plano(dados: Dataset) -> None:
    no_periodo = [e for e in dados.eventos if e.ocorrida_em.date() >= dados.inicio]
    assert len(dados.pessoas) == 40
    assert 370 <= len(dados.unidades) <= 400
    assert 13_000 <= len(no_periodo) <= 20_000
    assert (dados.inicio, dados.fim) == (date(2025, 9, 1), date(2026, 8, 31))


def test_eventos_em_ordem_e_dentro_do_periodo(dados: Dataset) -> None:
    instantes = [e.ocorrida_em for e in dados.eventos]
    assert instantes == sorted(instantes)
    assert instantes[-1] <= datetime.combine(dados.fim, time(23, 59, 59), tzinfo=cat.FUSO)


def test_quem_retira_esta_na_unidade(dados: Dataset) -> None:
    pessoas = {p.matricula: p for p in dados.pessoas}
    for e in dados.eventos:
        if e.operacao in ("retirada_unidade", "retirada_consumo"):
            assert e.pessoa is not None
            assert pessoas[e.pessoa].presente(e.ocorrida_em.date()), e


def test_saldo_nunca_fica_negativo(dados: Dataset) -> None:
    assert min(min(dias.values()) for dias in saldo_diario(dados).values()) >= 0


def test_estado_final_reconstruivel(dados: Dataset) -> None:
    estados = estado_final(dados)
    assert set(estados) == {u.ref for u in dados.unidades}
    for estado in estados.values():
        assert (estado.status == "CAUTELADA") == (estado.detentor is not None)
        assert (estado.bmp is None) == (estado.status == "AGUARDANDO_TOMBAMENTO")


def test_mudancas_de_situacao_so_por_quem_pode(dados: Dataset) -> None:
    perfil = {u.login: u.perfil for u in dados.usuarios}
    for e in dados.eventos:
        if e.operacao == "alterar_status":
            permitido = (
                {"ADMINISTRADOR"} if e.novo_status == "BAIXADA" else {"ADMINISTRADOR", "ESTOQUISTA"}
            )
            assert perfil[e.usuario] in permitido, e
        if e.operacao == "estorno":
            assert perfil[e.usuario] == "ADMINISTRADOR"


def test_estornos_na_quantidade_planejada(dados: Dataset) -> None:
    estornos = [e for e in dados.eventos if e.operacao == "estorno"]
    serial = [e for e in estornos if e.unidade is not None]
    assert len(serial) == cat.ESTORNOS_SERIAL
    assert 1 <= len(estornos) - len(serial) <= cat.ESTORNOS_CONSUMO


# ================================================================== P1 a P4: cautela
def test_p1_radios_voltam_no_fim_do_turno(dados: Dataset) -> None:
    radios = [
        c
        for c in cautelas(dados)
        if TIPOS[c.material].uso == "turno" and c.devolucao and c.saida.date() >= dados.inicio
    ]
    dias = [(c.devolucao.date() - c.saida.date()).days for c in radios if c.devolucao]
    assert 0.85 <= taxa([d == 0 for d in dias]) <= 0.93
    assert 0.03 <= taxa([d == 1 for d in dias]) <= 0.09
    # Saída entre 06:40 e 07:20; a correção de um lançamento errado (estorno) relança a
    # cautela 6 minutos depois, por isso o limite é 07:30.
    assert all(time(6, 40) <= c.saida.time() <= time(7, 30) for c in radios)


def test_p2_atraso_segue_o_perfil_da_pessoa(dados: Dataset) -> None:
    perfil = {p.matricula: p.perfil for p in dados.pessoas}
    comuns = [c for c in cautelas(dados) if c.devolucao and not TIPOS[c.material].eletrica]
    atraso = {pf: taxa([c.atrasada for c in comuns if perfil[c.pessoa] == pf]) for pf in cat.PERFIS}
    assert atraso["pontual"] <= 0.06
    assert 0.08 <= atraso["ocasional"] <= 0.25
    assert atraso["reincidente"] >= 0.30
    assert atraso["pontual"] < atraso["ocasional"] < atraso["reincidente"]


def test_p3_eletricas_atrasam_na_manutencao(dados: Dataset) -> None:
    setor = {p.matricula: p.setor for p in dados.pessoas}
    eletricas = [c for c in cautelas(dados) if c.devolucao and TIPOS[c.material].eletrica]
    manut = taxa([c.atrasada for c in eletricas if setor[c.pessoa] == "MANUT"])
    outros = taxa([c.atrasada for c in eletricas if setor[c.pessoa] != "MANUT"])
    assert manut >= 0.35
    assert outros <= 0.10


def test_p4_cautelas_de_transferidos_viram_nao_localizadas(dados: Dataset) -> None:
    pessoas = {p.matricula: p for p in dados.pessoas}
    estados = estado_final(dados)
    inventario = date.fromisoformat(cat.INVENTARIO_ANUAL)
    sem_devolucao = {c.unidade: c for c in cautelas(dados) if c.devolucao is None}
    casos = []
    for ref, estado in estados.items():
        cautela = sem_devolucao.get(ref)
        if estado.status == "NAO_LOCALIZADA" and cautela is not None:
            saida = pessoas[cautela.pessoa].data_saida
            assert saida is not None and cautela.saida.date() < saida < inventario
            assert (inventario - cautela.saida.date()).days > 60
            casos.append(ref)
    assert len(casos) == len(cat.TRANSFERIDOS_COM_MATERIAL)


# ================================================================== P5 a P7: uso
def test_p5_poucos_tipos_concentram_as_cautelas(dados: Dataset) -> None:
    por_tipo = cautelas_por_tipo(dados)
    cautelaveis = [t.codigo for t in cat.SERIAIS if t.prazo_h]
    contagens = sorted((por_tipo.get(c, 0) for c in cautelaveis), reverse=True)
    top = round(0.2 * len(cautelaveis))
    assert 0.78 <= sum(contagens[:top]) / sum(contagens) <= 0.90


def test_p6_tipos_sem_uso_e_sobra(dados: Dataset) -> None:
    por_tipo = cautelas_por_tipo(dados)
    sem_uso = {t.codigo for t in cat.SERIAIS if t.prazo_h and por_tipo.get(t.codigo, 0) == 0}
    assert sem_uso == {t.codigo for t in cat.SERIAIS if t.uso == "nenhum"}
    divisores = {c.unidade for c in cautelas(dados) if c.material == "SIN-0003"}
    assert len(divisores) == 3  # 10 divisores de fluxo, só 3 circulam


def test_p7_nos_dias_de_pico_todas_as_unidades_saem(dados: Dataset) -> None:
    faltas = {(dia, codigo) for dia, codigo, _ in dados.demanda_nao_atendida}
    for codigo in ("SIN-0004", "APO-0001"):
        total = TIPOS[codigo].unidades
        for dia in dados.dias_de_pico:
            meio_do_dia = datetime.combine(dia, time(12), tzinfo=cat.FUSO)
            fora = {
                c.unidade
                for c in cautelas(dados)
                if c.material == codigo
                and c.saida <= meio_do_dia
                and (c.devolucao is None or c.devolucao > meio_do_dia)
            }
            assert len(fora) == total, (codigo, dia)
            assert (dia, codigo) in faltas


# ================================================================== P8 a P11: consumo
def test_p8_consumo_so_em_dias_uteis(dados: Dataset) -> None:
    consumo = ("entrada_consumo", "retirada_consumo", "ajuste_consumo")
    assert all(e.ocorrida_em.weekday() < 5 for e in dados.eventos if e.operacao in consumo)


def _demanda_por_mes(dados: Dataset, codigos: set[str]) -> dict[int, float]:
    """Quantidade retirada por dia útil, em cada mês."""
    total: dict[int, int] = defaultdict(int)
    for e in dados.eventos:
        if e.operacao == "retirada_consumo" and e.material in codigos and e.quantidade:
            total[e.ocorrida_em.month] += e.quantidade
    dias_uteis = Counter(
        (dados.inicio + timedelta(days=i)).month
        for i in range((dados.fim - dados.inicio).days + 1)
        if (dados.inicio + timedelta(days=i)).weekday() < 5
    )
    return {mes: total[mes] / dias_uteis[mes] for mes in dias_uteis}


def test_p8_limpeza_tem_pico_em_janeiro(dados: Dataset) -> None:
    limpeza = {
        c.codigo for c in cat.CONSUMOS if c.sazonal == "janeiro" and CALIBRACAO[c.codigo] == "bom"
    }
    por_mes = _demanda_por_mes(dados, limpeza)
    normais = [v for m, v in por_mes.items() if m not in (1, 2, 12)]
    assert por_mes[1] >= 1.4 * sum(normais) / len(normais)


def test_p8_ferramentas_eletricas_tem_pico_em_marco_e_abril(dados: Dataset) -> None:
    por_mes = Counter(c.saida.month for c in cautelas(dados) if TIPOS[c.material].eletrica)
    pico = (por_mes[3] + por_mes[4]) / 2
    resto = [por_mes[m] for m in range(1, 13) if m not in (3, 4)]
    assert pico >= 1.3 * sum(resto) / len(resto)


def test_p9_p10_falta_se_concentra_nos_mal_calibrados(dados: Dataset) -> None:
    rupturas = rupturas_por_material(dados)
    for codigo, calibracao in CALIBRACAO.items():
        episodios, _ = rupturas[codigo]
        if calibracao == "mal_calibrado":
            assert episodios >= 4, codigo
        elif calibracao == "fornecedor_lento":
            assert episodios >= 1, codigo
        elif calibracao == "bom":
            assert episodios <= 3, codigo
    bons = [rupturas[c][0] for c, k in CALIBRACAO.items() if k == "bom"]
    assert sum(1 for e in bons if e == 0) >= 12  # a maioria nunca falta


def test_p10_minimo_mal_calibrado_abaixo_da_demanda_no_prazo(dados: Dataset) -> None:
    minimos = {s.codigo: s.minimo for s in dados.saldos}
    dias = (dados.fim - dados.inicio).days + 1
    retirado: Counter[str] = Counter()
    for e in dados.eventos:
        if e.operacao == "retirada_consumo" and e.quantidade:
            retirado[e.material] += e.quantidade
    for codigo, calibracao in CALIBRACAO.items():
        no_prazo = retirado[codigo] / dias * cat.PRAZO_REPOSICAO_PLANEJADO
        if calibracao == "mal_calibrado":
            assert minimos[codigo] < 0.6 * no_prazo, codigo
        elif calibracao == "bom":
            assert minimos[codigo] >= no_prazo, codigo


def test_p9_excesso_fica_acima_do_maximo(dados: Dataset) -> None:
    saldos = saldo_diario(dados)
    maximos = {s.codigo: s.maximo for s in dados.saldos}
    for codigo, calibracao in CALIBRACAO.items():
        if calibracao == "excesso":
            assert taxa([v > maximos[codigo] for v in saldos[codigo].values()]) >= 0.7


def test_p11_prazo_de_entrega_medido_pelas_entradas(dados: Dataset) -> None:
    prazos: dict[str, list[int]] = defaultdict(list)
    for e in dados.eventos:
        if e.operacao == "entrada_consumo" and e.observacao and e.observacao.startswith("Pedido"):
            pedido = date.fromisoformat(e.observacao.removeprefix("Pedido feito em "))
            prazos[CALIBRACAO[e.material]].append((e.ocorrida_em.date() - pedido).days)
    normais = prazos["bom"] + prazos["mal_calibrado"]
    assert min(normais) >= 7 and max(normais) <= 21 + 2  # +2: chegada adiada para dia útil
    assert min(prazos["fornecedor_lento"]) >= 25


# ================================================================== P12 a P16: planilha
def _taxas(planilha: list[Linha]) -> dict[str, float]:
    contagem = Counter(tipo for linha in planilha for (_, tipo, *_resto) in linha.erros)
    return {tipo: n / len(planilha) for tipo, n in contagem.items()}


def test_p12_a_p16_erros_frequentes_na_taxa_planejada(planilha: list[Linha]) -> None:
    t = _taxas(planilha)
    assert 0.18 <= t["nomenclatura_variante"] <= 0.32  # P12 (planejado 25%)
    assert 0.22 <= t["local_variante"] <= 0.38  # P16 (planejado 30%)
    assert 0.015 <= t["digitacao"] <= 0.07  # P13 (planejado 4%)


def test_p12_a_p16_erros_raros_presentes(planilha: list[Linha]) -> None:
    """Com taxa de 0,5% a 2% em ~360 linhas, espera-se de 2 a 7 ocorrências: uma faixa
    de taxa seria frágil (1 ocorrência a menos a derrubaria). Exige-se presença e um teto."""
    t = _taxas(planilha)
    raros = [
        "artefato_extracao",  # P13
        "bmp_ausente_erro",  # P14
        "bmp_ausente_legitimo",  # P14
        "bmp_digito_trocado",  # P14
        "serie_duplicada",  # P15
        "linha_duplicada",  # P15
        "divergencia_historico",  # P16
        "baixa_com_detentor",  # P16
    ]
    for tipo in raros:
        assert 0 < t.get(tipo, 0) <= 0.04, tipo


def test_p16_erros_concentrados_no_deposito_central(planilha: list[Linha]) -> None:
    especificos = ("bmp_ausente_legitimo", "divergencia_historico", "baixa_com_detentor")
    erros = [
        TIPOS[linha.material].local
        for linha in planilha
        for (_, tipo, *_resto) in linha.erros
        if tipo not in especificos
    ]
    assert 0.38 <= taxa([local == cat.LOCAL_CONCENTRA_ERROS for local in erros]) <= 0.55


def test_gabarito_descreve_o_que_esta_na_planilha(dados: Dataset, planilha: list[Linha]) -> None:
    unidades = {u.ref: u for u in dados.unidades}
    for linha in planilha:
        for _, tipo, campo, na_planilha, _correto in linha.erros:
            if tipo in ("nomenclatura_variante", "digitacao", "artefato_extracao"):
                # o último erro de nomenclatura aplicado é o que está na planilha
                continue
            if campo and tipo not in ("baixa_com_detentor", "divergencia_historico"):
                assert getattr(linha, campo) == na_planilha, (tipo, linha)
        assert linha.material == unidades[linha.unidade_ref].codigo
    nomes_errados = [
        linha for linha in planilha if linha.nomenclatura != TIPOS[linha.material].nome
    ]
    assert all(any(c == "nomenclatura" for _, _, c, _, _ in linha.erros) for linha in nomes_errados)


# ================================================================== reprodutibilidade
def test_mesma_semente_gera_arquivos_identicos(tmp_path: Path) -> None:
    hashes = []
    for pasta in ("a", "b"):
        d = gerar(7, "2026-06-30")
        hashes.append(gravar(d, gerar_planilha(d), tmp_path / pasta)["sha256"])
    assert hashes[0] == hashes[1]


def test_semente_diferente_gera_eventos_diferentes(tmp_path: Path) -> None:
    hashes = []
    for semente in (7, 8):
        d = gerar(semente, "2026-06-30")
        manifesto = gravar(d, gerar_planilha(d), tmp_path / str(semente))
        hashes.append(manifesto["sha256"]["eventos.csv"])  # type: ignore[index]
    assert hashes[0] != hashes[1]


def test_linha_de_comando_recusa_data_futura_ou_invalida() -> None:
    for data in ("2999-01-01", "31/08/2026"):
        with pytest.raises(SystemExit):
            cli.main(["--ate", data])
