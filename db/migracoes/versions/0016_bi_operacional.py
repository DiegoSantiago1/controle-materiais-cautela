"""bi operacional: posse, estoque e situação das unidades agora; operador e operação

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-02

O relatório operacional do Power BI (entradas e saídas, retiradas e devoluções, material
em posse, estoque, manutenção, movimentação por militar e por equipamentista) lê o banco
da APLICAÇÃO, o "sistema vivo". As views existem nos dois bancos (as migrações são as
mesmas); as "atuais" medem até agora (o relógio).

- dim_operador: quem opera o sistema (login, perfil, posto, nome de guerra);
- fato_movimentacao: ganha, no fim, o código de operação, os estados (retirada e
  devolução), a finalidade e o prazo (colunas novas só no fim: quem já usa a view não
  quebra);
- dim_material: ganha o estoque mínimo (de cada controle, numa coluna só);
- dim_calendario: começa na primeira retirada, se ela for anterior aos 12 meses;
- fato_posse_atual: cada unidade em posse agora, com quem entregou, prazo e atraso;
- fato_estoque_atual: os números de core.vw_estoque e o valor disponível;
- fato_unidade_atual: cada unidade, a situação e há quantos dias está nela (é o que
  responde "o que está em manutenção, e há quanto tempo").
Datas e horas em horário local (sem fuso), como nas views da 0011.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = r"""
-- Calendário: os 12 meses até a referência OU desde a primeira retirada, o que vier antes.
-- No banco das análises os dois dão 01/09/2025 (nada muda); no da aplicação a referência
-- anda com o uso, e sem isto o primeiro mês do histórico ficaria sem data no Power BI.
CREATE OR REPLACE VIEW bi.dim_calendario AS
WITH ref AS (
    SELECT core.data_local(analise.momento_referencia()) AS ultimo_dia,
           (SELECT core.data_local(min(ocorrida_em)) FROM core.movimentacao
            WHERE tipo = 'RETIRADA') AS primeira_retirada
)
SELECT d::date                                  AS data,
       extract(year FROM d)::int                AS ano,
       extract(month FROM d)::int               AS mes,
       to_char(d, 'YYYY-MM')                    AS ano_mes,
       extract(quarter FROM d)::int             AS trimestre,
       extract(isodow FROM d)::int              AS dia_da_semana,  -- 1 = segunda
       extract(isodow FROM d) < 6               AS dia_util
FROM ref, generate_series(
    least(ref.ultimo_dia - 364, coalesce(ref.primeira_retirada, ref.ultimo_dia - 364)),
    ref.ultimo_dia, interval '1 day') AS d;

CREATE VIEW bi.dim_operador AS
SELECT u.login, u.perfil, u.ativo, p.posto_graduacao, p.nome_guerra,
       p.posto_graduacao || ' ' || upper(p.nome_guerra) AS operador, p.nome
FROM core.usuario u
JOIN core.pessoa p ON p.id = u.pessoa_id;

CREATE OR REPLACE VIEW bi.dim_material AS
SELECT t.codigo, t.nome, c.nome AS categoria, s.nome AS subcategoria, t.controle,
       t.unidade_medida, t.prazo_devolucao_horas, t.custo_unitario, t.ativo,
       coalesce(t.estoque_minimo, sc.estoque_minimo) AS estoque_minimo
FROM core.material_tipo t
JOIN core.subcategoria s ON s.id = t.subcategoria_id
JOIN core.categoria c ON c.id = s.categoria_id
LEFT JOIN core.saldo_consumo sc ON sc.material_tipo_id = t.id;

CREATE OR REPLACE VIEW bi.fato_movimentacao AS
SELECT m.id,
       core.data_local(m.ocorrida_em)                         AS data,
       (m.ocorrida_em AT TIME ZONE 'America/Recife')          AS ocorrida_em,
       m.tipo,
       t.codigo                                               AS material,
       u.bmp,
       p.matricula                                            AS pessoa,
       us.login                                               AS executado_por,
       us.perfil                                              AS perfil_de_quem_executou,
       sd.sigla                                               AS setor_destino,
       coalesce(abs(m.variacao), 1)                           AS quantidade,
       m.variacao, m.saldo_antes, m.saldo_depois, m.status_anterior, m.status_novo,
       m.estorno_de_id IS NOT NULL                            AS e_estorno,
       coalesce(m.operacao::text, 'mov-' || m.id)             AS operacao,
       m.estado_retirada, m.estado_devolucao, m.finalidade,
       (m.prazo_devolucao AT TIME ZONE 'America/Recife')      AS prazo_devolucao,
       extract(hour FROM m.ocorrida_em AT TIME ZONE 'America/Recife')::int AS hora
FROM core.movimentacao m
JOIN core.material_tipo t ON t.id = m.material_tipo_id
JOIN core.usuario us ON us.id = m.executado_por
LEFT JOIN core.unidade_patrimonial u ON u.id = m.unidade_id
LEFT JOIN core.pessoa p ON p.id = m.pessoa_id
LEFT JOIN core.setor sd ON sd.id = m.setor_destino_id;

-- "Atual" é agora (o relógio). Os números congelados das análises continuam nas views do
-- schema analise, que usam a data de referência.
CREATE VIEW bi.fato_posse_atual AS
WITH agora AS (SELECT now() AS t)
SELECT v.bmp, v.codigo AS material, v.matricula AS pessoa,
       ue.login AS entregue_por,
       core.data_local(v.retirada_em)                      AS data_retirada,
       (v.retirada_em AT TIME ZONE 'America/Recife')       AS retirada_em,
       (v.prazo AT TIME ZONE 'America/Recife')             AS prazo,
       v.prazo < agora.t                                   AS vencida,
       round(extract(epoch FROM agora.t - v.retirada_em) / 3600, 1) AS horas_em_posse,
       round(greatest(extract(epoch FROM agora.t - v.prazo), 0) / 3600, 1) AS horas_de_atraso,
       coalesce(v.operacao::text, 'mov-' || v.retirada_id) AS operacao,
       v.estado_retirada, v.finalidade
FROM core.vw_posse v
CROSS JOIN agora
JOIN core.usuario ue ON ue.id = v.entregue_por_usuario_id;

CREATE VIEW bi.fato_estoque_atual AS
SELECT codigo AS material, total, disponivel, em_posse, em_manutencao, indisponivel,
       estoque_minimo, situacao, situacao <> 'NORMAL' AS em_alerta,
       round(disponivel * custo_unitario, 2) AS valor_disponivel
FROM core.vw_estoque;

CREATE VIEW bi.fato_unidade_atual AS
WITH agora AS (SELECT now() AS t),
ultima AS (
    SELECT DISTINCT ON (unidade_id) unidade_id, ocorrida_em
    FROM core.movimentacao
    WHERE unidade_id IS NOT NULL
    ORDER BY unidade_id, ocorrida_em DESC, id DESC
)
SELECT u.bmp, t.codigo AS material, u.status, l.nome AS local, p.matricula AS pessoa,
       (ul.ocorrida_em AT TIME ZONE 'America/Recife') AS na_situacao_desde,
       round(extract(epoch FROM agora.t - ul.ocorrida_em) / 86400, 1) AS dias_na_situacao
FROM core.unidade_patrimonial u
CROSS JOIN agora
JOIN core.material_tipo t ON t.id = u.material_tipo_id
JOIN core.local_armazenagem l ON l.id = u.local_id
LEFT JOIN core.pessoa p ON p.id = u.detentor_id
JOIN ultima ul ON ul.unidade_id = u.id;
"""

# As views novas já nascem legíveis pelo grupo do BI (default privileges da 0011). Isto
# só garante, caso o grupo tenha sido criado depois da 0011.
PERMISSOES = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_leitura') THEN
        GRANT SELECT ON bi.dim_operador, bi.fato_posse_atual, bi.fato_estoque_atual,
                        bi.fato_unidade_atual TO almox_leitura;
    END IF;
END;
$$;
"""

VIEWS_ANTIGAS = r"""
CREATE OR REPLACE VIEW bi.dim_calendario AS
WITH ref AS (SELECT core.data_local(analise.momento_referencia()) AS ultimo_dia)
SELECT d::date                                  AS data,
       extract(year FROM d)::int                AS ano,
       extract(month FROM d)::int               AS mes,
       to_char(d, 'YYYY-MM')                    AS ano_mes,
       extract(quarter FROM d)::int             AS trimestre,
       extract(isodow FROM d)::int              AS dia_da_semana,  -- 1 = segunda
       extract(isodow FROM d) < 6               AS dia_util
FROM ref, generate_series(ref.ultimo_dia - 364, ref.ultimo_dia, interval '1 day') AS d;

DROP VIEW bi.fato_unidade_atual;
DROP VIEW bi.fato_estoque_atual;
DROP VIEW bi.fato_posse_atual;
DROP VIEW bi.dim_operador;

DROP VIEW bi.fato_movimentacao;
CREATE VIEW bi.fato_movimentacao AS
SELECT m.id,
       core.data_local(m.ocorrida_em)                         AS data,
       (m.ocorrida_em AT TIME ZONE 'America/Recife')          AS ocorrida_em,
       m.tipo,
       t.codigo                                               AS material,
       u.bmp,
       p.matricula                                            AS pessoa,
       us.login                                               AS executado_por,
       us.perfil                                              AS perfil_de_quem_executou,
       sd.sigla                                               AS setor_destino,
       coalesce(abs(m.variacao), 1)                           AS quantidade,
       m.variacao, m.saldo_antes, m.saldo_depois, m.status_anterior, m.status_novo,
       m.estorno_de_id IS NOT NULL                            AS e_estorno
FROM core.movimentacao m
JOIN core.material_tipo t ON t.id = m.material_tipo_id
JOIN core.usuario us ON us.id = m.executado_por
LEFT JOIN core.unidade_patrimonial u ON u.id = m.unidade_id
LEFT JOIN core.pessoa p ON p.id = m.pessoa_id
LEFT JOIN core.setor sd ON sd.id = m.setor_destino_id;

DROP VIEW bi.dim_material;
CREATE VIEW bi.dim_material AS
SELECT t.codigo, t.nome, c.nome AS categoria, s.nome AS subcategoria, t.controle,
       t.unidade_medida, t.prazo_devolucao_horas, t.custo_unitario, t.ativo
FROM core.material_tipo t
JOIN core.subcategoria s ON s.id = t.subcategoria_id
JOIN core.categoria c ON c.id = s.categoria_id;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_leitura') THEN
        GRANT SELECT ON bi.fato_movimentacao, bi.dim_material TO almox_leitura;
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute(VIEWS)
    op.execute(PERMISSOES)


def downgrade() -> None:
    op.execute(VIEWS_ANTIGAS)
