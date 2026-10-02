"""Materiais operacionais do banco da APLICAÇÃO (controle de distúrbios, proteção
balística, formatura e cerimonial, paraquedismo, campanha, EPI e comunicação) e os
militares apresentados junto com eles.

Por que só no banco da aplicação (decisão D23): as análises e o Power BI das análises
leem o banco congelado em 31/08/2026, com números já validados contra o gabarito. Estes
materiais chegam depois, como uma incorporação de carga em 01/09/2026, no "sistema vivo".

Tudo entra pelas funções de regra (registrar_entrada_unidade, cadastrar_saldo_consumo,
registrar_entrada_consumo), com BMP sequencial a partir de 6.100.001 (faixa fora da usada
pelo gerador) e dados 100% fictícios. Sem armamento (decisão do PLAN): tonfa, espadim e
sabre entram por serem material de choque e de cerimonial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from almox.banco import Conexao, chamar_funcao

INCORPORADO_EM = datetime(2026, 9, 1, 7, 0, tzinfo=ZoneInfo("America/Recife"))
PRIMEIRO_BMP = 6_100_001

RESERVA = "Reserva de Equipamentos"
APOIO = "Área de Apoio"
CONSUMO = "Almoxarifado de Consumo"


@dataclass(frozen=True)
class Material:
    """Material patrimonial (cada unidade com BMP), cautelável por prazo_h horas."""

    codigo: str
    nome: str
    subcategoria: str
    unidades: int
    prazo_h: int
    custo: float
    local: str
    minimo: int


@dataclass(frozen=True)
class Consumo:
    """Material de consumo: só quantidade (sai e não volta)."""

    codigo: str
    nome: str
    subcategoria: str
    unidade_medida: str
    saldo_inicial: int
    minimo: int
    maximo: int
    custo: float


# categoria -> subcategorias (criadas se ainda não existirem)
CATEGORIAS = {
    "Operacional": [
        "Controle de distúrbios",
        "Proteção balística",
        "Formatura e cerimonial",
        "Paraquedismo",
        "Campanha",
    ],
    "Proteção individual": ["EPI permanente"],
    "Comunicações": ["Rádios portáteis", "Acessórios de comunicação", "Energia e carregadores"],
}

MATERIAIS = [
    # --- controle de distúrbios (tropa de choque): treino à tarde, volta no mesmo dia
    Material("CHQ-0001", "Escudo antitumulto de policarbonato", "Controle de distúrbios", 24, 12, 1200, RESERVA, 8),
    Material("CHQ-0002", "Capacete antitumulto com viseira", "Controle de distúrbios", 24, 12, 900, RESERVA, 8),
    Material("CHQ-0003", "Colete de proteção antitumulto", "Controle de distúrbios", 24, 12, 1500, RESERVA, 8),
    Material("CHQ-0004", "Tonfa de polímero", "Controle de distúrbios", 24, 12, 180, RESERVA, 8),
    Material("CHQ-0005", "Caneleira de proteção antitumulto (par)", "Controle de distúrbios", 24, 12, 350, RESERVA, 8),
    Material("CHQ-0006", "Protetor de antebraço (par)", "Controle de distúrbios", 24, 12, 250, RESERVA, 8),
    Material("CHQ-0007", "Máscara de proteção respiratória", "Controle de distúrbios", 20, 12, 800, RESERVA, 6),
    Material("CHQ-0008", "Luva tática anticorte (par)", "Controle de distúrbios", 24, 12, 160, RESERVA, 8),
    Material("CHQ-0009", "Protetor de virilha", "Controle de distúrbios", 20, 12, 120, RESERVA, 6),
    # --- proteção balística: sai com o serviço armado (24 h)
    Material("BAL-0001", "Colete de proteção balística nível III-A", "Proteção balística", 30, 24, 3500, RESERVA, 10),
    Material("BAL-0002", "Capacete balístico", "Proteção balística", 15, 24, 4200, RESERVA, 5),
    # --- formatura e cerimonial: sai na véspera, volta depois da solenidade
    Material("FOR-0001", "Capacete de formatura branco", "Formatura e cerimonial", 40, 96, 220, RESERVA, 10),
    Material("FOR-0002", "Cinto de gala branco", "Formatura e cerimonial", 40, 96, 90, RESERVA, 10),
    Material("FOR-0003", "Luvas brancas de formatura (par)", "Formatura e cerimonial", 60, 96, 35, RESERVA, 15),
    Material("FOR-0004", "Polainas brancas (par)", "Formatura e cerimonial", 40, 96, 70, RESERVA, 10),
    Material("FOR-0005", "Cordão de gala", "Formatura e cerimonial", 30, 96, 60, RESERVA, 8),
    Material("FOR-0006", "Boina de formatura", "Formatura e cerimonial", 40, 96, 60, RESERVA, 10),
    Material("FOR-0007", "Talabarte porta-bandeira", "Formatura e cerimonial", 4, 96, 150, RESERVA, 2),
    Material("FOR-0008", "Bandeira Nacional de mastro", "Formatura e cerimonial", 4, 96, 450, RESERVA, 2),
    Material("FOR-0009", "Pavilhão Nacional de desfile", "Formatura e cerimonial", 2, 96, 900, RESERVA, 1),
    Material("FOR-0010", "Estandarte da unidade", "Formatura e cerimonial", 2, 96, 1200, RESERVA, 1),
    Material("FOR-0011", "Mastro de bandeira com base", "Formatura e cerimonial", 6, 96, 380, RESERVA, 2),
    Material("FOR-0012", "Espadim de formatura com bainha", "Formatura e cerimonial", 20, 96, 420, RESERVA, 5),
    Material("FOR-0013", "Sabre de oficial com bainha", "Formatura e cerimonial", 8, 96, 950, RESERVA, 2),
    Material("FOR-0014", "Fiel de sabre", "Formatura e cerimonial", 10, 96, 45, RESERVA, 3),
    # --- paraquedismo: sai para a semana de salto
    Material("PQD-0001", "Paraquedas principal", "Paraquedismo", 20, 72, 18000, RESERVA, 6),
    Material("PQD-0002", "Paraquedas reserva", "Paraquedismo", 20, 72, 12000, RESERVA, 6),
    Material("PQD-0003", "Capacete de salto", "Paraquedismo", 20, 72, 900, RESERVA, 6),
    Material("PQD-0004", "Altímetro de pulso", "Paraquedismo", 12, 72, 1400, RESERVA, 4),
    Material("PQD-0005", "Óculos de salto", "Paraquedismo", 20, 72, 120, RESERVA, 6),
    Material("PQD-0006", "Macacão de salto", "Paraquedismo", 20, 72, 600, RESERVA, 6),
    Material("PQD-0007", "Bolsa de equipamento de salto", "Paraquedismo", 10, 72, 700, RESERVA, 3),
    Material("PQD-0008", "Saco de transporte de paraquedas", "Paraquedismo", 25, 72, 260, RESERVA, 6),
    Material("PQD-0009", "Faca de gancho corta-linhas", "Paraquedismo", 20, 72, 140, RESERVA, 6),
    Material("PQD-0010", "Luvas de salto (par)", "Paraquedismo", 20, 72, 110, RESERVA, 6),
    # --- campanha: sai para exercícios de vários dias
    Material("CPA-0001", "Barraca individual", "Campanha", 30, 168, 450, APOIO, 8),
    Material("CPA-0002", "Saco de dormir", "Campanha", 30, 168, 300, APOIO, 8),
    Material("CPA-0003", "Mochila de campanha 60 L", "Campanha", 30, 168, 400, APOIO, 8),
    Material("CPA-0004", "Cantil com porta-cantil", "Campanha", 40, 168, 80, APOIO, 10),
    Material("CPA-0005", "Rede de selva com mosquiteiro", "Campanha", 25, 168, 180, APOIO, 6),
    Material("CPA-0006", "Poncho impermeável", "Campanha", 30, 168, 120, APOIO, 8),
    Material("CPA-0007", "Cinto de guarnição", "Campanha", 40, 168, 110, APOIO, 10),
    Material("CPA-0008", "Colete tático modular", "Campanha", 20, 168, 650, APOIO, 6),
    Material("CPA-0009", "Bússola de campanha", "Campanha", 15, 168, 150, APOIO, 4),
    Material("CPA-0010", "Binóculo 10x50", "Campanha", 8, 168, 900, APOIO, 2),
    Material("CPA-0011", "Lanterna de cabeça", "Campanha", 30, 168, 95, APOIO, 8),
    Material("CPA-0012", "Corda estática 30 m", "Campanha", 12, 168, 380, APOIO, 4),
    Material("CPA-0013", "Mosquetão de aço com trava", "Campanha", 40, 168, 55, APOIO, 10),
    Material("CPA-0014", "Pá de campanha dobrável", "Campanha", 20, 168, 130, APOIO, 5),
    Material("CPA-0015", "Facão com bainha", "Campanha", 20, 168, 90, APOIO, 5),
    Material("CPA-0016", "Machadinha de campanha", "Campanha", 10, 168, 120, APOIO, 3),
    Material("CPA-0017", "Fogareiro portátil", "Campanha", 10, 168, 210, APOIO, 3),
    Material("CPA-0018", "Marmita de campanha", "Campanha", 30, 168, 45, APOIO, 8),
    Material("CPA-0019", "Mochila de assalto 30 L", "Campanha", 20, 168, 280, APOIO, 6),
    # --- EPI permanente (o descartável é material de consumo): tarefas do dia
    Material("EPP-0001", "Capacete de segurança com jugular", "EPI permanente", 30, 24, 90, APOIO, 8),
    Material("EPP-0002", "Protetor auricular tipo concha", "EPI permanente", 30, 24, 80, APOIO, 8),
    Material("EPP-0003", "Cinto de segurança para trabalho em altura", "EPI permanente", 10, 24, 450, APOIO, 3),
    Material("EPP-0004", "Óculos de proteção ampla visão", "EPI permanente", 40, 24, 45, APOIO, 10),
    Material("EPP-0005", "Luva de vaqueta (par)", "EPI permanente", 40, 24, 40, APOIO, 10),
    Material("EPP-0006", "Colete refletivo", "EPI permanente", 40, 24, 30, APOIO, 10),
    Material("EPP-0007", "Coturno de reserva (par)", "EPI permanente", 30, 168, 260, APOIO, 8),
    Material("EPP-0008", "Capa de chuva", "EPI permanente", 30, 24, 85, APOIO, 8),
    Material("EPP-0009", "Bota de borracha (par)", "EPI permanente", 20, 24, 75, APOIO, 5),
    Material("EPP-0010", "Protetor facial incolor", "EPI permanente", 15, 24, 60, APOIO, 4),
    Material("EPP-0011", "Luva de raspa (par)", "EPI permanente", 30, 24, 28, APOIO, 8),
    Material("EPP-0012", "Respirador semifacial com filtro", "EPI permanente", 15, 24, 140, APOIO, 4),
    # --- comunicação e apoio: o kit do serviço de dia (24 h)
    Material("COM-0001", "Rádio portátil UHF tático RP-300", "Rádios portáteis", 25, 24, 2800, RESERVA, 8),
    Material("COM-0002", "Bateria extra de rádio portátil", "Acessórios de comunicação", 40, 24, 320, RESERVA, 12),
    Material("COM-0003", "Fone de ouvido com PTT", "Acessórios de comunicação", 25, 24, 260, RESERVA, 8),
    Material("COM-0004", "Microfone de lapela", "Acessórios de comunicação", 20, 24, 210, RESERVA, 6),
    Material("COM-0005", "Antena flexível sobressalente", "Acessórios de comunicação", 20, 72, 90, RESERVA, 5),
    Material("COM-0006", "Cabo de programação de rádio", "Acessórios de comunicação", 4, 24, 150, RESERVA, 1),
    Material("COM-0007", "Carregador múltiplo de 6 rádios", "Energia e carregadores", 6, 72, 1100, RESERVA, 2),
    Material("COM-0008", "Carregador veicular de rádio", "Energia e carregadores", 10, 72, 240, RESERVA, 3),
    Material("COM-0009", "Bateria externa (power bank) 20.000 mAh", "Energia e carregadores", 15, 72, 180, RESERVA, 4),
    Material("COM-0010", "Cabo de extensão elétrica 20 m", "Energia e carregadores", 10, 72, 120, RESERVA, 3),
]  # fmt: skip

CONSUMOS = [
    Consumo("PIL-0001", "Pilha alcalina AA (cartela com 4)", "Energia e carregadores", "PCT", 180, 40, 300, 22),
    Consumo("PIL-0002", "Pilha alcalina AAA (cartela com 4)", "Energia e carregadores", "PCT", 90, 20, 200, 20),
    Consumo("LUZ-0001", "Bastão de luz química", "Campanha", "UN", 120, 50, 400, 9),
    Consumo("FIT-0001", "Fita adesiva silver tape", "Campanha", "ROLO", 25, 10, 60, 28),
]  # fmt: skip


# Militares apresentados em 01/09/2026 (o efetivo do quartel cresceu com a chegada do
# material operacional). Matrículas fora da faixa do gerador (3.000.000 a 6.999.999).
NOVOS_MILITARES = [
    ("7100001", "S1", "Carlos Eduardo Silva", "Silva", "SEG"),
    ("7100002", "SGT", "Renato Souza", "Souza", "SEG"),
    ("7100003", "S2", "Lucas Ramos", "Ramos", "SEG"),
    ("7100004", "S2", "Diego Moreira", "Moreira", "SEG"),
    ("7100005", "S1", "Marcos Freire", "Freire", "SEG"),
    ("7100006", "CB", "Thiago Teixeira", "Teixeira", "SEG"),
    ("7100007", "S2", "Rafael Lacerda", "Lacerda", "SEG"),
    ("7100008", "S1", "Igor Medeiros", "Medeiros", "SEG"),
    ("7100009", "CB", "Vinícius Cardoso", "Cardoso", "SEG"),
    ("7100010", "S2", "Pedro Galvão", "Galvão", "SEG"),
    ("7100011", "S1", "Amanda Arruda", "Arruda", "OPER"),
    ("7100012", "SGT", "Fábio Pimentel", "Pimentel", "OPER"),
    ("7100013", "S2", "Caio Rocha", "Rocha", "OPER"),
    ("7100014", "S1", "Daniel Batista", "Batista", "OPER"),
    ("7100015", "CB", "Letícia Magalhães", "Magalhães", "OPER"),
    ("7100016", "S2", "Henrique Correia", "Correia", "OPER"),
    ("7100017", "S1", "Mariana Holanda", "Holanda", "OPER"),
    ("7100018", "CB", "Rodrigo Barbosa", "Barbosa", "OPER"),
    ("7100019", "S2", "Gabriel Cunha", "Cunha", "MANUT"),
    ("7100020", "S1", "Camila Sales", "Sales", "MANUT"),
    ("7100021", "SGT", "Eduardo Leite", "Leite", "MANUT"),
    ("7100022", "S2", "Arthur Feitosa", "Feitosa", "SAUDE"),
    ("7100023", "TEN", "Paula Amorim", "Amorim", "OPER"),
    ("7100024", "S1", "Bruno Pessoa Neto", "Neto", "TI"),
]
APRESENTACAO = date(2026, 9, 1)


def _id(con: Conexao, sql: str, parametros: list[object]) -> int:
    linha = con.execute(sql, parametros).fetchone()
    if linha is None:
        raise RuntimeError(f"nada devolvido: {sql}")
    return int(linha[0])


def _subcategorias(con: Conexao) -> dict[str, int]:
    """Cria as categorias e subcategorias que faltarem; devolve nome -> id."""
    ids: dict[str, int] = {}
    for categoria, subcategorias in CATEGORIAS.items():
        id_categoria = _id(
            con,
            "INSERT INTO core.categoria (nome) VALUES (%s) "
            "ON CONFLICT ((lower(nome))) DO UPDATE SET nome = EXCLUDED.nome RETURNING id",
            [categoria],
        )
        for nome in subcategorias:
            ids[nome] = _id(
                con,
                "INSERT INTO core.subcategoria (categoria_id, nome) VALUES (%s, %s) "
                "ON CONFLICT (categoria_id, (lower(nome))) DO UPDATE SET nome = EXCLUDED.nome "
                "RETURNING id",
                [id_categoria, nome],
            )
    return ids


def carregar_complemento(con: Conexao) -> int:
    """Cadastra os materiais e incorpora as unidades e os saldos iniciais. Devolve quantas
    unidades patrimoniais entraram. Roda como o dono do banco, na transação de quem chama."""
    estoquista = _id(
        con, "SELECT min(id) FROM core.usuario WHERE perfil = 'ESTOQUISTA' AND ativo", []
    )
    for matricula, posto, nome, guerra, setor in NOVOS_MILITARES:
        con.execute(
            "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, posto_graduacao, "
            "nome_guerra) SELECT %s, %s, id, %s, %s, %s FROM core.setor WHERE sigla = %s",
            [matricula, nome, APRESENTACAO, posto, guerra, setor],
        )
    subcategoria = _subcategorias(con)
    local = {
        nome: _id(con, "SELECT id FROM core.local_armazenagem WHERE nome = %s", [nome])
        for nome in (RESERVA, APOIO, CONSUMO)
    }

    bmp = PRIMEIRO_BMP
    for m in MATERIAIS:
        id_material = _id(
            con,
            "INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, "
            "controle, prazo_devolucao_horas, custo_unitario, estoque_minimo) "
            "VALUES (%s, %s, %s, 'UN', 'SERIAL', %s, %s, %s) RETURNING id",
            [m.codigo, m.nome, subcategoria[m.subcategoria], m.prazo_h, m.custo, m.minimo],
        )
        for _ in range(m.unidades):
            chamar_funcao(
                con,
                "registrar_entrada_unidade",
                p_material_tipo_id=id_material,
                p_local_id=local[m.local],
                p_executado_por=estoquista,
                p_bmp=str(bmp),
                p_ocorrida_em=INCORPORADO_EM,
                p_documento_ref="Incorporação de material operacional",
            )
            bmp += 1

    for c in CONSUMOS:
        id_material = _id(
            con,
            "INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, "
            "controle, custo_unitario) VALUES (%s, %s, %s, %s, 'CONSUMO', %s) RETURNING id",
            [c.codigo, c.nome, subcategoria[c.subcategoria], c.unidade_medida, c.custo],
        )
        chamar_funcao(
            con,
            "cadastrar_saldo_consumo",
            p_material_tipo_id=id_material,
            p_local_id=local[CONSUMO],
            p_estoque_minimo=c.minimo,
            p_estoque_maximo=c.maximo,
            p_executado_por=estoquista,
        )
        chamar_funcao(
            con,
            "registrar_entrada_consumo",
            p_material_tipo_id=id_material,
            p_quantidade=c.saldo_inicial,
            p_executado_por=estoquista,
            p_ocorrida_em=INCORPORADO_EM,
            p_documento_ref="Saldo inicial",
        )
    return bmp - PRIMEIRO_BMP
