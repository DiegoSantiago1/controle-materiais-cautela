"""analise: consumo diário, rupturas, prazo de entrega e status do estoque (A4)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24

- vw_consumo_diario: por material de consumo e por dia do período, a saída líquida do
  dia (retiradas menos estornos de retirada) e o saldo no fim do dia (a última
  movimentação até aquele dia, buscada com LATERAL no índice (material, ocorrida_em)).
- vw_ruptura: episódios de falta. Dias com saldo zero que se sucedem formam um
  episódio: técnica "gaps and islands" (dia - row_number() é constante dentro de uma
  sequência de dias consecutivos).
- vw_prazo_entrega: prazo real de cada compra. A data do pedido está na observação da
  entrada ("Pedido feito em AAAA-MM-DD"), como numa nota de empenho.
- vw_status_consumo: situação atual de cada saldo contra o mínimo e o máximo.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = r"""
CREATE VIEW analise.vw_consumo_diario AS
WITH ref AS (
    SELECT core.data_local(analise.momento_referencia()) AS ultimo_dia
),
dias AS (
    SELECT generate_series(ref.ultimo_dia - 364, ref.ultimo_dia, interval '1 day')::date AS dia
    FROM ref
),
saidas AS (
    -- Saída líquida: retirada conta positivo; o estorno de uma retirada devolve.
    SELECT m.material_tipo_id, core.data_local(m.ocorrida_em) AS dia, -sum(m.variacao) AS saida
    FROM core.movimentacao m
    LEFT JOIN core.movimentacao o ON o.id = m.estorno_de_id
    WHERE m.controle = 'CONSUMO'
      AND (m.tipo = 'RETIRADA' OR (m.tipo = 'ESTORNO' AND o.tipo = 'RETIRADA'))
    GROUP BY 1, 2
)
SELECT s.material_tipo_id, t.codigo, t.nome, d.dia,
       coalesce(sa.saida, 0)::integer AS saida,
       ultimo.saldo_depois AS saldo_fim_do_dia,
       s.estoque_minimo, s.estoque_maximo
FROM core.saldo_consumo s
JOIN core.material_tipo t ON t.id = s.material_tipo_id
CROSS JOIN dias d
LEFT JOIN saidas sa ON sa.material_tipo_id = s.material_tipo_id AND sa.dia = d.dia
-- JOIN (e não LEFT JOIN): os dias anteriores à primeira movimentação do material ficam
-- de fora. Com LEFT JOIN eles viriam com saldo zero, e um material cadastrado no meio
-- do período "faltaria" em todos os dias antes de existir.
JOIN LATERAL (
    SELECT m.saldo_depois
    FROM core.movimentacao m
    WHERE m.material_tipo_id = s.material_tipo_id
      AND m.ocorrida_em < (d.dia + 1)::timestamp AT TIME ZONE 'America/Recife'
    ORDER BY m.ocorrida_em DESC, m.id DESC
    LIMIT 1
) ultimo ON true;

COMMENT ON VIEW analise.vw_consumo_diario IS
    'Saída líquida e saldo no fim do dia, por material de consumo, nos 365 dias (A4).';

CREATE VIEW analise.vw_ruptura AS
WITH zerados AS (
    SELECT codigo, nome, dia,
           -- Gaps and islands: dentro de uma sequência de dias consecutivos,
           -- dia - (posição na sequência) é constante; esse valor identifica a ilha.
           dia - (row_number() OVER (PARTITION BY codigo ORDER BY dia))::integer AS ilha
    FROM analise.vw_consumo_diario
    WHERE saldo_fim_do_dia = 0
)
SELECT codigo, nome, min(dia) AS inicio, max(dia) AS fim, count(*) AS dias
FROM zerados
GROUP BY codigo, nome, ilha;

COMMENT ON VIEW analise.vw_ruptura IS
    'Episódios de falta: dias consecutivos com saldo zero no fim do dia (A4).';

CREATE VIEW analise.vw_prazo_entrega AS
WITH entradas AS (
    SELECT m.id, t.codigo, t.nome, m.documento_ref, m.variacao AS quantidade,
           core.data_local(m.ocorrida_em) AS recebido_em,
           substring(m.observacao FROM 'Pedido feito em (\d{4}-\d{2}-\d{2})')::date AS pedido_em
    FROM core.movimentacao m
    JOIN core.material_tipo t ON t.id = m.material_tipo_id
    WHERE m.controle = 'CONSUMO' AND m.tipo = 'ENTRADA'
)
SELECT *, recebido_em - pedido_em AS prazo_dias
FROM entradas
WHERE pedido_em IS NOT NULL;

CREATE VIEW analise.vw_status_consumo AS
SELECT t.codigo, t.nome, sub.nome AS subcategoria, t.unidade_medida, t.custo_unitario,
       s.quantidade, s.estoque_minimo, s.estoque_maximo,
       CASE
           WHEN NOT t.ativo THEN 'INATIVO'
           WHEN s.quantidade = 0 THEN 'SEM_ESTOQUE'
           WHEN s.quantidade <= 0.5 * s.estoque_minimo THEN 'CRITICO'
           WHEN s.quantidade <= s.estoque_minimo THEN 'BAIXO'
           WHEN s.quantidade > s.estoque_maximo THEN 'ACIMA_DO_MAXIMO'
           ELSE 'NORMAL'
       END AS status,
       greatest(s.quantidade - s.estoque_maximo, 0) * t.custo_unitario AS valor_acima_do_maximo
FROM core.saldo_consumo s
JOIN core.material_tipo t ON t.id = s.material_tipo_id
JOIN core.subcategoria sub ON sub.id = t.subcategoria_id;

COMMENT ON VIEW analise.vw_status_consumo IS
    'Situação atual de cada material de consumo contra o mínimo e o máximo.';
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW analise.vw_status_consumo;
        DROP VIEW analise.vw_prazo_entrega;
        DROP VIEW analise.vw_ruptura;
        DROP VIEW analise.vw_consumo_diario;
        """
    )
