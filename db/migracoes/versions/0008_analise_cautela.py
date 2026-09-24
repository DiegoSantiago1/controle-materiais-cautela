"""analise: cautelas reconstruídas do histórico e atrasos (A2)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24

A cautela não tem tabela própria: é reconstruída do histórico. Cada RETIRADA de uma
unidade é pareada com a movimentação seguinte da mesma unidade (window function LEAD):
uma DEVOLUCAO fecha a cautela; uma MUDANCA_STATUS para NAO_LOCALIZADA a encerra como
perdida; nada depois dela = cautela ainda aberta.

Estornos saem da sequência ANTES do pareamento: a movimentação estornada e o próprio
estorno se anulam. Sem isso, "retirada -> estorno -> retirada" pareia errado.

Data de referência: o instante da última movimentação registrada (e não now()), para
que a análise dos dados gerados seja a mesma em qualquer dia em que for rodada.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = r"""
CREATE FUNCTION analise.momento_referencia() RETURNS timestamptz
LANGUAGE sql STABLE AS $$
    SELECT max(ocorrida_em) FROM core.movimentacao
$$;

CREATE VIEW analise.vw_cautela AS
WITH valida AS (
    -- Histórico das unidades sem os pares (movimentação estornada, estorno).
    SELECT m.*
    FROM core.movimentacao m
    WHERE m.controle = 'SERIAL'
      AND m.tipo <> 'ESTORNO'
      AND NOT EXISTS (SELECT 1 FROM core.movimentacao e WHERE e.estorno_de_id = m.id)
),
sequencia AS (
    SELECT v.*,
           lead(v.tipo)        OVER w AS proximo_tipo,
           lead(v.ocorrida_em) OVER w AS proximo_em,
           lead(v.status_novo) OVER w AS proximo_status,
           lead(v.estado_devolucao) OVER w AS proximo_estado
    FROM valida v
    WINDOW w AS (PARTITION BY v.unidade_id ORDER BY v.ocorrida_em, v.id)
),
ref AS (SELECT analise.momento_referencia() AS agora)
SELECT
    s.id                AS retirada_id,
    s.unidade_id,
    u.bmp,
    t.codigo            AS material,
    t.nome              AS material_nome,
    sub.nome            AS subcategoria,
    p.id                AS pessoa_id,
    p.matricula,
    p.nome              AS pessoa,
    se.sigla            AS setor,
    s.ocorrida_em       AS retirada_em,
    s.prazo_devolucao   AS prazo,
    CASE WHEN s.proximo_tipo = 'DEVOLUCAO' THEN s.proximo_em END AS devolvida_em,
    s.proximo_estado    AS estado_na_devolucao,
    CASE
        WHEN s.proximo_tipo = 'DEVOLUCAO' THEN 'DEVOLVIDA'
        WHEN s.proximo_status = 'NAO_LOCALIZADA' THEN 'NAO_LOCALIZADA'
        WHEN s.proximo_tipo IS NULL THEN 'EM_ABERTO'
        ELSE 'OUTRO'
    END AS situacao,
    -- Atrasada: devolvida depois do prazo, ou ainda fora (aberta ou perdida) com o
    -- prazo vencido na data de referência.
    coalesce(CASE WHEN s.proximo_tipo = 'DEVOLUCAO' THEN s.proximo_em END, ref.agora)
        > s.prazo_devolucao AS atrasada,
    greatest(
        extract(epoch FROM coalesce(CASE WHEN s.proximo_tipo = 'DEVOLUCAO' THEN s.proximo_em END,
                                    ref.agora) - s.prazo_devolucao) / 86400.0,
        0)::numeric(10, 2) AS dias_de_atraso,
    (extract(epoch FROM coalesce(CASE WHEN s.proximo_tipo = 'DEVOLUCAO' THEN s.proximo_em END,
                                 ref.agora) - s.ocorrida_em) / 3600.0)::numeric(10, 2)
        AS horas_com_a_pessoa,
    -- Devolvida no mesmo dia (local) da retirada: o regime de turno dos rádios.
    s.proximo_tipo = 'DEVOLUCAO'
        AND core.data_local(s.proximo_em) = core.data_local(s.ocorrida_em) AS mesmo_dia
FROM sequencia s
CROSS JOIN ref
JOIN core.unidade_patrimonial u ON u.id = s.unidade_id
JOIN core.material_tipo t ON t.id = s.material_tipo_id
JOIN core.subcategoria sub ON sub.id = t.subcategoria_id
JOIN core.pessoa p ON p.id = s.pessoa_id
JOIN core.setor se ON se.id = p.setor_id
WHERE s.tipo = 'RETIRADA';

COMMENT ON VIEW analise.vw_cautela IS
    'Uma linha por cautela (retirada de unidade), reconstruída do histórico com LEAD (A2).';

-- Atraso por pessoa, com posição geral e dentro do setor.
CREATE VIEW analise.vw_atraso_pessoa AS
WITH por_pessoa AS (
    SELECT pessoa_id, matricula, pessoa, setor,
           count(*)                                   AS cautelas,
           count(*) FILTER (WHERE atrasada)           AS atrasadas,
           round(avg(atrasada::int), 4)               AS taxa_atraso,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY dias_de_atraso)
               FILTER (WHERE atrasada)                AS mediana_dias_atraso,
           count(*) FILTER (WHERE situacao <> 'DEVOLVIDA') AS ainda_fora
    FROM analise.vw_cautela
    GROUP BY pessoa_id, matricula, pessoa, setor
)
SELECT *,
       rank() OVER (ORDER BY taxa_atraso DESC, atrasadas DESC) AS posicao_geral,
       rank() OVER (PARTITION BY setor
                    ORDER BY taxa_atraso DESC, atrasadas DESC) AS posicao_no_setor
FROM por_pessoa;

-- Atraso por setor e subcategoria de material.
CREATE VIEW analise.vw_atraso_setor_material AS
SELECT setor, subcategoria,
       count(*)                          AS cautelas,
       count(*) FILTER (WHERE atrasada)  AS atrasadas,
       round(avg(atrasada::int), 4)      AS taxa_atraso,
       round(avg(dias_de_atraso) FILTER (WHERE atrasada), 2) AS media_dias_atraso
FROM analise.vw_cautela
GROUP BY setor, subcategoria;
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW analise.vw_atraso_setor_material;
        DROP VIEW analise.vw_atraso_pessoa;
        DROP VIEW analise.vw_cautela;
        DROP FUNCTION analise.momento_referencia();
        """
    )
