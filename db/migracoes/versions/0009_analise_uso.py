"""analise: uso, ociosidade, falta, desgaste e curva ABC do material cautelável (A3)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-24

Duas linhas do tempo por tipo de material, construídas só a partir do histórico
(sem os pares estorno/estornada), com somas acumuladas (window functions):

- capacidade: unidades em circulação (DISPONIVEL ou CAUTELADA). Cada movimentação muda
  a capacidade em (em circulação depois) - (em circulação antes): uma unidade que entra
  em manutenção, some ou é baixada deixa de contar; uma que volta, conta de novo;
- unidades fora: +1 quando a unidade passa a CAUTELADA, -1 quando deixa de estar.

Com as duas, no período de 12 meses até a data de referência:
- utilização = horas cauteladas / horas-unidade em circulação;
- pico de uso simultâneo; horas esgotado (todas as unidades em circulação estavam fora);
- sobra: unidades na carga que não saíram nenhuma vez, e o valor parado nelas;
- desgaste: unidades baixadas no período;
- curva ABC pelo número de cautelas.

Contar as unidades "de hoje" daria resultado errado: o que foi baixado durante o ano
(ex.: lanterna que quebrou) sumiria da conta e a utilização passaria de 100%.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = r"""
-- Histórico das unidades sem os pares (movimentação estornada, estorno): a sequência
-- "como se o erro não tivesse acontecido". Base das análises de uso.
CREATE VIEW analise.vw_historico_serial_valido AS
SELECT m.*
FROM core.movimentacao m
WHERE m.controle = 'SERIAL'
  AND m.tipo <> 'ESTORNO'
  AND NOT EXISTS (SELECT 1 FROM core.movimentacao e WHERE e.estorno_de_id = m.id);

CREATE VIEW analise.vw_uso_material AS
WITH ref AS (
    SELECT analise.momento_referencia() AS agora,
           analise.momento_referencia() - interval '1 year' AS inicio
),
tipos AS (
    SELECT t.id, t.codigo, t.nome, sub.nome AS subcategoria, t.custo_unitario
    FROM core.material_tipo t
    JOIN core.subcategoria sub ON sub.id = t.subcategoria_id
    WHERE t.controle = 'SERIAL' AND t.prazo_devolucao_horas IS NOT NULL
),
variacoes AS (
    SELECT h.material_tipo_id, h.ocorrida_em AS instante, h.id,
           (h.status_novo IN ('DISPONIVEL', 'CAUTELADA'))::int
             - coalesce((h.status_anterior IN ('DISPONIVEL', 'CAUTELADA'))::int, 0) AS d_capacidade,
           (h.status_novo = 'CAUTELADA')::int
             - coalesce((h.status_anterior = 'CAUTELADA')::int, 0)                  AS d_fora
    FROM analise.vw_historico_serial_valido h
    JOIN tipos t ON t.id = h.material_tipo_id
),
acumulado AS (
    SELECT material_tipo_id, instante,
           sum(d_capacidade) OVER w AS capacidade,
           sum(d_fora)       OVER w AS fora,
           lead(instante)    OVER (PARTITION BY material_tipo_id ORDER BY instante, id)
               AS proximo
    FROM variacoes
    WINDOW w AS (PARTITION BY material_tipo_id ORDER BY instante, id ROWS UNBOUNDED PRECEDING)
),
-- Cada intervalo entre duas movimentações, recortado ao período analisado.
intervalos AS (
    SELECT a.material_tipo_id, a.capacidade, a.fora,
           extract(epoch FROM least(coalesce(a.proximo, ref.agora), ref.agora)
                              - greatest(a.instante, ref.inicio)) / 3600.0 AS horas
    FROM acumulado a, ref
    WHERE coalesce(a.proximo, ref.agora) > ref.inicio AND a.instante < ref.agora
),
linha_do_tempo AS (
    SELECT material_tipo_id,
           max(fora)                                           AS pico_simultaneo,
           sum(horas * capacidade)                             AS horas_unidade,
           sum(horas * fora)                                   AS horas_cauteladas,
           sum(horas) FILTER (WHERE fora >= capacidade AND capacidade > 0) AS horas_esgotado
    FROM intervalos
    GROUP BY material_tipo_id
),
cautelas AS (
    SELECT h.material_tipo_id, count(*) AS cautelas, count(DISTINCT h.unidade_id) AS usadas
    FROM analise.vw_historico_serial_valido h, ref
    WHERE h.tipo = 'RETIRADA' AND h.ocorrida_em > ref.inicio
    GROUP BY h.material_tipo_id
),
unidades AS (
    SELECT u.material_tipo_id,
           count(*) FILTER (WHERE u.status <> 'BAIXADA') AS na_carga,
           count(*) FILTER (
               WHERE u.status <> 'BAIXADA'
                 AND NOT EXISTS (
                     SELECT 1 FROM analise.vw_historico_serial_valido h, ref
                     WHERE h.unidade_id = u.id AND h.tipo = 'RETIRADA'
                       AND h.ocorrida_em > ref.inicio)
           ) AS paradas,
           count(*) FILTER (
               WHERE EXISTS (
                   SELECT 1 FROM analise.vw_historico_serial_valido h, ref
                   WHERE h.unidade_id = u.id AND h.status_novo = 'BAIXADA'
                     AND h.ocorrida_em > ref.inicio)
           ) AS baixadas_no_periodo
    FROM core.unidade_patrimonial u
    GROUP BY u.material_tipo_id
),
base AS (
    SELECT
        t.codigo, t.nome, t.subcategoria, t.custo_unitario,
        coalesce(u.na_carga, 0)                    AS unidades_na_carga,
        coalesce(c.cautelas, 0)                    AS cautelas,
        coalesce(c.usadas, 0)                      AS unidades_usadas,
        round((l.horas_cauteladas / nullif(l.horas_unidade, 0))::numeric, 4) AS utilizacao,
        coalesce(l.pico_simultaneo, 0)             AS pico_simultaneo,
        round(coalesce(l.horas_esgotado, 0)::numeric, 1) AS horas_esgotado,
        coalesce(u.paradas, 0)                     AS unidades_paradas,
        coalesce(u.paradas, 0) * t.custo_unitario  AS valor_parado,
        coalesce(u.baixadas_no_periodo, 0)         AS baixadas_no_periodo
    FROM tipos t
    LEFT JOIN linha_do_tempo l ON l.material_tipo_id = t.id
    LEFT JOIN cautelas c ON c.material_tipo_id = t.id
    LEFT JOIN unidades u ON u.material_tipo_id = t.id
)
SELECT
    b.*,
    round(b.cautelas::numeric / nullif(sum(b.cautelas) OVER (), 0), 4) AS participacao,
    -- Classe ABC: a participação acumulada ATÉ A LINHA ANTERIOR (ordem decrescente de
    -- uso) decide. A = tipos que, somados do mais usado ao menos, formam os primeiros 80%.
    CASE
        WHEN b.cautelas = 0 THEN 'SEM USO'
        WHEN coalesce(sum(b.cautelas) OVER w_antes, 0) < 0.80 * sum(b.cautelas) OVER () THEN 'A'
        WHEN coalesce(sum(b.cautelas) OVER w_antes, 0) < 0.95 * sum(b.cautelas) OVER () THEN 'B'
        ELSE 'C'
    END AS classe_abc,
    b.horas_esgotado > 0 AS ja_esgotou
FROM base b
WINDOW w_antes AS (ORDER BY b.cautelas DESC, b.codigo
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING);

COMMENT ON VIEW analise.vw_uso_material IS
    'Uso, pico simultâneo, falta, sobra, desgaste e classe ABC por tipo cautelável (A3).';
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW analise.vw_uso_material;
        DROP VIEW analise.vw_historico_serial_valido;
        """
    )
