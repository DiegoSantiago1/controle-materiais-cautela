"""Parâmetros do gerador: catálogo fictício, pessoas, taxas e padrões (P1 a P16).

Tudo que vira número no README sai daqui. Nenhum dado é real: materiais, nomes,
números e locais foram inventados para uma organização logística genérica.
Não há armamento, munição nem material de armaria.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone

# Recife não tem horário de verão desde 2019: fuso fixo -03:00.
FUSO = timezone(timedelta(hours=-3))
SEMENTE_PADRAO = 42
ANCORA_PADRAO = "2026-08-31"  # último dia do período (12 meses)


# ============================================================ estrutura
CATEGORIAS: dict[str, list[str]] = {
    "Comunicações": ["Rádios portáteis", "Rádios fixos e repetidoras", "Acessórios de comunicação"],
    "Ferramentas": ["Ferramentas elétricas", "Ferramentas manuais", "Instrumentos de medição"],
    "Informática": ["Computadores e periféricos", "Suprimentos de informática"],
    "Sinalização e apoio": ["Sinalização", "Apoio e campanha", "Primeiros socorros", "Iluminação"],
    "Mobiliário e utilidades": ["Mobiliário", "Utilidades"],
    "Expediente": ["Papelaria"],
    "Limpeza": ["Produtos de limpeza", "Descartáveis"],
    "Manutenção predial": ["Material elétrico", "Fixação"],
    "Proteção individual": ["EPI descartável"],
}

SETORES: dict[str, str] = {
    "SEG": "Segurança e Guarda",
    "OPER": "Operações",
    "MANUT": "Manutenção",
    "ADM": "Administração",
    "TI": "Tecnologia da Informação",
    "SAUDE": "Seção de Saúde",
}

LOCAIS = [
    "Depósito Central",
    "Reserva de Equipamentos",
    "Sala de Ferramentas",
    "Almoxarifado de Consumo",
    "Sala de Informática",
    "Área de Apoio",
    "Seção de Manutenção",
    "Instalações Administrativas",
]


# ============================================================ material patrimonial
@dataclass(frozen=True)
class TipoSerial:
    codigo: str
    nome: str
    subcategoria: str
    unidades: int
    prazo_h: int | None  # None = não cautelável
    custo: float
    local: str
    uso: str  # "turno" (rádio), "eventual", "nenhum" (sem uso no ano), "fixo" (não sai)
    taxa_dia: float = 0.0  # pedidos de cautela por dia (eventual)
    fim_de_semana: bool = False  # também é pedido em sábados e domingos
    duracao_h: tuple[float, float] = (2.0, 8.0)  # uso típico, dentro do prazo
    setores: tuple[str, ...] = ("OPER",)
    serie: str | None = None  # prefixo do número de série (None = sem série)
    unidades_usadas: int | None = None  # P6: só as N primeiras unidades circulam
    eventos_pico: bool = False  # P7: dias de solenidade com demanda acima do estoque
    eletrica: bool = False  # P3 e P8: ferramentas elétricas
    ano_aquisicao: tuple[int, int] = (2016, 2024)


SERIAIS: list[TipoSerial] = [
    # --- P1: rádios em regime de turno (retira ~07:00, devolve ~19:00)
    TipoSerial("RAD-0001", "Rádio portátil VHF RP-100", "Rádios portáteis", 40, 12, 2500,
               "Reserva de Equipamentos", "turno", setores=("SEG", "OPER"), serie="RP1",
               ano_aquisicao=(2016, 2018)),
    TipoSerial("RAD-0002", "Rádio portátil VHF digital RP-200", "Rádios portáteis", 30, 12, 3200,
               "Reserva de Equipamentos", "turno", setores=("SEG", "OPER"), serie="RP2",
               ano_aquisicao=(2021, 2023)),
    TipoSerial("RAD-0003", "Rádio móvel veicular RM-50", "Rádios fixos e repetidoras", 6, 72,
               4200, "Reserva de Equipamentos", "eventual", taxa_dia=0.30, duracao_h=(8, 60),
               setores=("OPER",), serie="RM5"),
    TipoSerial("RAD-0004", "Estação repetidora transportável ER-10",
               "Rádios fixos e repetidoras", 2, 168, 18000, "Reserva de Equipamentos", "nenhum",
               serie="ER1"),
    TipoSerial("ACS-0001", "Carregador de bateria de rádio", "Acessórios de comunicação", 20,
               None, 250, "Reserva de Equipamentos", "fixo"),
    # --- ferramentas (P3, P8: elétricas com atraso concentrado na Manutenção e pico mar/abr)
    TipoSerial("FER-0001", "Furadeira de impacto 800 W", "Ferramentas elétricas", 6, 168, 450,
               "Sala de Ferramentas", "eventual", taxa_dia=0.40, duracao_h=(4, 120),
               setores=("MANUT", "MANUT", "MANUT", "ADM"), serie="FI8", eletrica=True),
    TipoSerial("FER-0002", "Parafusadeira a bateria 12 V", "Ferramentas elétricas", 5, 168, 600,
               "Sala de Ferramentas", "eventual", taxa_dia=0.35, duracao_h=(4, 120),
               setores=("MANUT", "MANUT", "TI"), serie="PB1", eletrica=True),
    TipoSerial("FER-0003", "Esmerilhadeira angular 1300 W", "Ferramentas elétricas", 3, 168, 380,
               "Sala de Ferramentas", "eventual", taxa_dia=0.20, duracao_h=(4, 96),
               setores=("MANUT",), serie="EA1", eletrica=True),
    TipoSerial("FER-0004", "Lavadora de alta pressão", "Ferramentas elétricas", 2, 72, 900,
               "Sala de Ferramentas", "eventual", taxa_dia=0.15, duracao_h=(3, 30),
               setores=("MANUT", "ADM"), serie="LA1", eletrica=True),
    TipoSerial("FER-0005", "Caixa de ferramentas 65 peças", "Ferramentas manuais", 6, 168, 700,
               "Sala de Ferramentas", "eventual", taxa_dia=0.50, duracao_h=(3, 100),
               setores=("MANUT", "MANUT", "TI", "OPER")),
    TipoSerial("FER-0006", "Maleta de ferramentas para eletrônica", "Ferramentas manuais", 4,
               168, 550, "Sala de Ferramentas", "eventual", taxa_dia=0.25, duracao_h=(3, 72),
               setores=("TI", "MANUT")),
    TipoSerial("FER-0007", "Alicate hidráulico de compressão", "Ferramentas manuais", 2, 168,
               1200, "Sala de Ferramentas", "nenhum"),
    TipoSerial("MED-0001", "Multímetro digital", "Instrumentos de medição", 4, 72, 250,
               "Sala de Ferramentas", "eventual", taxa_dia=0.30, duracao_h=(2, 48),
               setores=("MANUT", "TI"), serie="MD1"),
    TipoSerial("MED-0002", "Testador de cabos de rede", "Instrumentos de medição", 3, 72, 180,
               "Sala de Informática", "nenhum", serie="TC1"),
    # --- sinalização, apoio e iluminação
    TipoSerial("SIN-0001", "Cone de sinalização refletivo", "Sinalização", 30, 72, 60,
               "Área de Apoio", "eventual", taxa_dia=0.90, duracao_h=(3, 48),
               setores=("SEG", "OPER")),
    TipoSerial("SIN-0002", "Bastão sinalizador luminoso", "Sinalização", 12, 12, 45,
               "Área de Apoio", "eventual", taxa_dia=1.20, fim_de_semana=True,
               duracao_h=(4, 11), setores=("SEG",)),
    TipoSerial("SIN-0003", "Divisor de fluxo com fita retrátil", "Sinalização", 10, 72, 320,
               "Área de Apoio", "eventual", taxa_dia=0.15, duracao_h=(3, 30),
               setores=("OPER", "ADM"), unidades_usadas=3),  # P6: sobra
    TipoSerial("SIN-0004", "Megafone portátil", "Sinalização", 3, 24, 300, "Área de Apoio",
               "eventual", taxa_dia=0.05, duracao_h=(2, 10), setores=("OPER", "SEG"),
               eventos_pico=True),  # P7: falta
    TipoSerial("APO-0001", "Escada extensível de alumínio", "Apoio e campanha", 2, 24, 800,
               "Área de Apoio", "eventual", taxa_dia=0.10, duracao_h=(2, 10),
               setores=("MANUT",), eventos_pico=True),  # P7: falta
    TipoSerial("APO-0002", "Maca de campanha dobrável", "Apoio e campanha", 20, 72, 700,
               "Depósito Central", "nenhum"),
    TipoSerial("APO-0003", "Barraca modular de campanha", "Apoio e campanha", 4, 168, 2500,
               "Depósito Central", "nenhum"),
    TipoSerial("ILU-0001", "Lanterna tática recarregável", "Iluminação", 15, 12, 150,
               "Reserva de Equipamentos", "eventual", taxa_dia=2.00, fim_de_semana=True,
               duracao_h=(4, 11), setores=("SEG", "SEG", "OPER")),
    TipoSerial("PSO-0001", "Maleta de primeiros socorros", "Primeiros socorros", 4, 72, 350,
               "Depósito Central", "eventual", taxa_dia=0.10, duracao_h=(4, 48),
               setores=("SAUDE", "OPER")),
    TipoSerial("INF-0001", "Notebook de serviço", "Computadores e periféricos", 6, 168, 4500,
               "Sala de Informática", "eventual", taxa_dia=0.50, duracao_h=(8, 150),
               setores=("TI", "ADM", "OPER"), serie="NB5"),
    TipoSerial("INF-0002", "Projetor multimídia", "Computadores e periféricos", 2, 24, 3000,
               "Sala de Informática", "eventual", taxa_dia=0.10, duracao_h=(2, 8),
               setores=("ADM", "OPER"), serie="PJ3"),
    TipoSerial("INF-0003", "Estabilizador de câmera", "Computadores e periféricos", 1, 72, 900,
               "Sala de Informática", "nenhum", serie="EC1"),
    # --- patrimônio fixo (não cautelável)
    TipoSerial("MOB-0001", "Armário de aço 2 portas", "Mobiliário", 25, None, 900,
               "Instalações Administrativas", "fixo", ano_aquisicao=(2010, 2020)),
    TipoSerial("MOB-0002", "Estante de aço 6 prateleiras", "Mobiliário", 30, None, 600,
               "Depósito Central", "fixo", ano_aquisicao=(2010, 2020)),
    TipoSerial("MOB-0003", "Mesa de trabalho angular", "Mobiliário", 15, None, 800,
               "Instalações Administrativas", "fixo", ano_aquisicao=(2012, 2022)),
    TipoSerial("MOB-0004", "Cadeira giratória com braços", "Mobiliário", 25, None, 500,
               "Instalações Administrativas", "fixo", ano_aquisicao=(2015, 2023)),
    TipoSerial("INF-0004", "Microcomputador desktop", "Computadores e periféricos", 12, None,
               3500, "Instalações Administrativas", "fixo", serie="DT8",
               ano_aquisicao=(2019, 2022)),
    TipoSerial("INF-0005", "Monitor LED 21,5 polegadas", "Computadores e periféricos", 15, None,
               800, "Instalações Administrativas", "fixo", serie="MN2",
               ano_aquisicao=(2019, 2022)),
    TipoSerial("UTL-0001", "Bebedouro de coluna", "Utilidades", 4, None, 700,
               "Instalações Administrativas", "fixo", serie="BB3"),
    TipoSerial("UTL-0002", "Condicionador de ar split 12000 BTU", "Utilidades", 6, None, 2500,
               "Instalações Administrativas", "fixo", serie="AC1"),
]  # fmt: skip

# P1: rádios por dia (média; distribuição de Poisson), dias úteis e fim de semana.
RADIOS_POR_DIA_UTIL = 12.0
RADIOS_POR_DIA_FIM_DE_SEMANA = 6.0

# P7: dias de solenidade no ano, com pedidos acima do número de unidades.
DIAS_DE_PICO = 8

# Probabilidade de dano na devolução (rádio / demais).
PROB_AVARIA = {"turno": 0.005, "outros": 0.02}
PROB_INSERVIVEL = {"turno": 0.001, "outros": 0.004}
PROB_MANUTENCAO_VIRA_BAIXA = 0.20
OBSERVACOES_AVARIA = [
    "Antena quebrada",
    "Bateria não segura carga",
    "Botão com defeito",
    "Carcaça trincada",
    "Não liga",
    "Cabo de alimentação danificado",
]

# Aquisições no período: (data, código, quantidade, com BMP).
AQUISICOES = [
    ("2025-11-10", "FER-0001", 2, True),
    ("2026-07-20", "FER-0001", 3, False),
    ("2026-07-20", "FER-0002", 3, False),
    ("2026-07-20", "MED-0001", 2, False),
]
TOMBAMENTO = ("2026-08-12", 5)  # data e quantas das unidades sem BMP recebem número

# Patrimônio fixo: baixas e itens não encontrados no inventário anual.
INVENTARIO_ANUAL = "2026-06-15"
FIXOS_PARA_BAIXA = [("MOB-0004", 3), ("MOB-0001", 1)]  # viram BAIXA_PENDENTE
FIXOS_BAIXADOS = 2  # destes, quantos chegam a BAIXADA no período
FIXOS_NAO_ENCONTRADOS = [("MOB-0004", 1)]

# Estornos por lançamento errado (cautela na pessoa errada, quantidade errada).
ESTORNOS_SERIAL = 10
ESTORNOS_CONSUMO = 5


# ============================================================ pessoas (P2, P3, P4)
PESSOAS_POR_SETOR = {"SEG": 12, "OPER": 8, "MANUT": 7, "ADM": 6, "TI": 4, "SAUDE": 3}
# P2: perfis de pontualidade na devolução (probabilidade de atrasar uma cautela).
PERFIS = {"pontual": 0.03, "ocasional": 0.15, "reincidente": 0.40}
QTD_PERFIS = {"reincidente": 4, "ocasional": 8}  # o restante é pontual
# P3: na Manutenção, ferramentas elétricas atrasam com esta probabilidade mínima.
PROB_ATRASO_ELETRICA_MANUT = 0.45
# P4: transferidos que saem com material cautelado e nunca devolvem.
TRANSFERIDOS_COM_MATERIAL = [("ILU-0001", "2025-12-04"), ("MED-0001", "2026-01-20"),
                             ("INF-0001", "2026-03-09")]  # fmt: skip
TRANSFERIDOS_SEM_PENDENCIA = 1
CHEGADAS_NO_PERIODO = ["2025-11-03", "2026-01-12", "2026-03-02", "2026-05-04"]

USUARIOS = [  # (perfil, setor da pessoa)
    ("ADMINISTRADOR", "ADM"),
    ("ESTOQUISTA", "ADM"),
    ("ESTOQUISTA", "ADM"),
    ("EQUIPAMENTISTA", "SEG"),
    ("EQUIPAMENTISTA", "SEG"),
    ("EQUIPAMENTISTA", "SEG"),
    ("EQUIPAMENTISTA", "SEG"),
    ("CONSULTA", "OPER"),
    ("CONSULTA", "MANUT"),
]

NOMES = [
    "Ana",
    "Bruno",
    "Carla",
    "Diego",
    "Eduarda",
    "Felipe",
    "Gabriela",
    "Heitor",
    "Isabela",
    "João",
    "Karina",
    "Lucas",
    "Mariana",
    "Nicolas",
    "Olívia",
    "Paulo",
    "Rafaela",
    "Samuel",
    "Tatiane",
    "Vinícius",
    "Yasmin",
    "André",
    "Beatriz",
    "Caio",
    "Débora",
    "Enzo",
    "Fernanda",
    "Gustavo",
    "Helena",
    "Igor",
    "Júlia",
    "Leonardo",
    "Larissa",
    "Mateus",
    "Natália",
    "Otávio",
    "Priscila",
    "Renato",
    "Sabrina",
    "Thiago",
    "Vanessa",
    "Wagner",
]
SOBRENOMES = ["Albuquerque", "Barros", "Cavalcanti", "Duarte", "Esteves", "Farias", "Gouveia",
              "Holanda", "Lins", "Macedo", "Nogueira", "Oliveira", "Pacheco", "Queiroz", "Rego",
              "Siqueira", "Tavares", "Uchoa", "Valença", "Xavier", "Brandão", "Coutinho",
              "Figueiredo", "Guerra", "Leão", "Moura", "Pessoa", "Rocha", "Sales", "Torres"]  # fmt: skip


# ============================================================ consumo (P8 a P11)
@dataclass(frozen=True)
class TipoConsumo:
    codigo: str
    nome: str
    subcategoria: str
    unidade: str
    custo: float
    pedidos_dia: float  # pedidos por dia útil
    tamanho: tuple[int, int]  # unidades por pedido (mín, máx)
    sazonal: str | None  # "trimestre", "janeiro", "mar_abr" ou None
    calibracao: str  # "bom", "mal_calibrado", "fornecedor_lento", "excesso"
    setores: tuple[str, ...]
    minimo_fixo: int | None = None  # história do toner: mínimo cadastrado 5


CONSUMOS: list[TipoConsumo] = [
    TipoConsumo("EXP-0001", "Papel A4 75 g", "Papelaria", "RESMA", 28, 1.2, (1, 5), "trimestre", "bom", ("ADM", "OPER", "TI")),
    TipoConsumo("EXP-0002", "Caneta esferográfica azul", "Papelaria", "CX", 35, 0.3, (1, 2), "trimestre", "bom", ("ADM", "OPER")),
    TipoConsumo("EXP-0003", "Grampo 26/6", "Papelaria", "CX", 8, 0.15, (1, 2), "trimestre", "excesso", ("ADM",)),
    TipoConsumo("EXP-0004", "Pasta suspensa", "Papelaria", "PCT", 45, 0.2, (1, 2), "trimestre", "bom", ("ADM",)),
    TipoConsumo("EXP-0005", "Envelope pardo A4", "Papelaria", "PCT", 30, 0.15, (1, 3), "trimestre", "excesso", ("ADM", "OPER")),
    TipoConsumo("EXP-0006", "Fita adesiva transparente", "Papelaria", "ROLO", 6, 0.25, (1, 4), "trimestre", "bom", ("ADM", "OPER", "MANUT")),
    TipoConsumo("INF-0101", "Toner para impressora laser", "Suprimentos de informática", "UN", 320, 0.8, (1, 3), "trimestre", "mal_calibrado", ("ADM", "TI"), minimo_fixo=5),
    TipoConsumo("INF-0102", "Cartucho de tinta preta", "Suprimentos de informática", "UN", 90, 0.3, (1, 2), "trimestre", "mal_calibrado", ("ADM", "OPER")),
    TipoConsumo("LIM-0001", "Desinfetante", "Produtos de limpeza", "GL", 18, 0.6, (1, 3), "janeiro", "bom", ("ADM", "SAUDE")),
    TipoConsumo("LIM-0002", "Detergente neutro", "Produtos de limpeza", "FRASCO", 3, 0.6, (1, 4), "janeiro", "bom", ("ADM",)),
    TipoConsumo("LIM-0003", "Saco de lixo 100 L", "Descartáveis", "PCT", 25, 0.7, (1, 3), "janeiro", "mal_calibrado", ("ADM", "MANUT")),
    TipoConsumo("LIM-0004", "Papel higiênico", "Descartáveis", "PCT", 20, 1.0, (1, 4), "janeiro", "bom", ("ADM",)),
    TipoConsumo("LIM-0005", "Papel toalha", "Descartáveis", "PCT", 15, 0.8, (1, 4), "janeiro", "bom", ("ADM", "SAUDE")),
    TipoConsumo("LIM-0006", "Álcool 70%", "Produtos de limpeza", "L", 9, 0.5, (1, 4), "janeiro", "fornecedor_lento", ("SAUDE", "ADM")),
    TipoConsumo("LIM-0007", "Luva de borracha", "Produtos de limpeza", "PAR", 5, 0.3, (1, 3), "janeiro", "bom", ("ADM",)),
    TipoConsumo("LIM-0008", "Sabão em pó", "Produtos de limpeza", "KG", 12, 0.2, (1, 3), "janeiro", "excesso", ("ADM",)),
    TipoConsumo("MAN-0001", "Pilha AA", "Material elétrico", "PCT", 22, 0.5, (1, 3), "mar_abr", "bom", ("SEG", "MANUT", "OPER")),
    TipoConsumo("MAN-0002", "Fita isolante", "Material elétrico", "ROLO", 7, 0.3, (1, 3), "mar_abr", "bom", ("MANUT",)),
    TipoConsumo("MAN-0003", "Lâmpada LED 9 W", "Material elétrico", "UN", 12, 0.4, (1, 6), "mar_abr", "bom", ("MANUT",)),
    TipoConsumo("MAN-0004", "Abraçadeira de nylon", "Fixação", "PCT", 14, 0.2, (1, 2), "mar_abr", "bom", ("MANUT", "TI")),
    TipoConsumo("MAN-0005", "Parafuso sortido", "Fixação", "CX", 40, 0.15, (1, 2), "mar_abr", "bom", ("MANUT",)),
    TipoConsumo("EPI-0001", "Luva de proteção", "EPI descartável", "PAR", 9, 0.4, (1, 4), None, "bom", ("MANUT", "ADM")),
    TipoConsumo("EPI-0002", "Máscara descartável", "EPI descartável", "CX", 25, 0.3, (1, 2), None, "bom", ("SAUDE", "ADM")),
    TipoConsumo("EPI-0003", "Protetor auricular", "EPI descartável", "PAR", 4, 0.2, (1, 5), None, "bom", ("MANUT",)),
]  # fmt: skip

# P8: multiplicador da demanda por mês (1 a 12).
SAZONALIDADE: dict[str, dict[int, float]] = {
    "trimestre": {3: 1.5, 6: 1.5, 9: 1.5, 12: 1.5},
    "janeiro": {1: 1.8, 2: 1.2, 12: 1.2},
    "mar_abr": {3: 1.6, 4: 1.6},
}
SAZONALIDADE_ELETRICAS = {3: 1.6, 4: 1.6}  # P8 também nas cautelas de ferramentas elétricas

# P11: prazo de reposição (dias corridos), por calibração.
PRAZO_REPOSICAO = {"normal": (7, 21), "fornecedor_lento": (25, 45)}
ANOS_DE_DEMANDA_NO_EXCESSO = 1.2  # P9: compra exagerada, acima do máximo o ano inteiro
PRAZO_REPOSICAO_PLANEJADO = 14  # o que o cadastro "assume" ao definir o mínimo
Z_SERVICO = 1.65  # ~95% de nível de serviço no cálculo do mínimo bem calibrado
DIAS_COBERTURA_MAXIMO = 30  # máximo = mínimo + um mês de demanda
DIAS_COBERTURA_MAL_CALIBRADO = 60  # lotes maiores: menos ciclos, mas falta em quase todos

# Inventário trimestral do consumo: chance de achar diferença em cada item.
INVENTARIOS_CONSUMO = ["2025-11-28", "2026-02-27", "2026-05-29", "2026-08-28"]
PROB_DIFERENCA_INVENTARIO = 0.35


# ============================================================ planilha suja (P12 a P16)
TAXAS_ERRO = {
    "nomenclatura_variante": 0.25,  # P12
    "digitacao": 0.04,  # P13
    "artefato_extracao": 0.02,  # P13
    "bmp_ausente_erro": 0.015,  # P14 (a outra metade é legítima: sem tombamento)
    "bmp_digito_trocado": 0.01,  # P14
    "serie_duplicada": 0.015,  # P15
    "linha_duplicada": 0.005,  # P15
    "local_variante": 0.30,  # P16
    "baixa_com_detentor": 0.01,  # P16
    "divergencia_historico": 0.02,  # P16
}
LOCAL_CONCENTRA_ERROS = "Depósito Central"
# Linhas desse local recebem erros com peso 4,5. Com ~16% das linhas nesse local, isso
# leva ~45% dos erros para lá: 0,16·4,5 / (0,16·4,5 + 0,84) ≈ 0,46.
MULTIPLICADOR_LOCAL_ERROS = 4.5
