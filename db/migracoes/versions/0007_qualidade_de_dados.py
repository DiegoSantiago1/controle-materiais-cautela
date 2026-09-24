"""schema dq: checagens de qualidade de dados com registro das ocorrências

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24

O que o banco já impede na origem (código duplicado, saldo negativo, movimentação sem
usuário ou sem material, quantidade zero, data no futuro...) não vira checagem aqui:
uma checagem que nunca pode encontrar nada é teatro. Essas garantias estão nas
constraints e são provadas pelos testes de schema.

As checagens deste schema cobrem o que constraints não conseguem expressar: regras
entre linhas (encadeamento do histórico), entre tabelas (estado x histórico, pessoa x
data) e sobre dados crus (staging). Cada regra é uma view `dq.chk_*` que devolve as
ocorrências; `dq.executar()` roda todas e grava o resultado em `dq.ocorrencia`.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESTRUTURA = r"""
CREATE SCHEMA dq;
COMMENT ON SCHEMA dq IS 'Qualidade de dados: regras, execuções e ocorrências.';

CREATE TABLE dq.regra (
    codigo      text PRIMARY KEY CONSTRAINT ck_regra_codigo CHECK (codigo ~ '^DQ[0-9]{2}$'),
    descricao   text NOT NULL,
    severidade  text NOT NULL
                CONSTRAINT ck_regra_severidade CHECK (severidade IN ('CRITICA', 'ALTA', 'MEDIA')),
    -- View que implementa a regra; devolve (referencia, detalhe).
    visao       text NOT NULL UNIQUE CONSTRAINT ck_regra_visao CHECK (visao ~ '^chk_[a-z_]+$')
);

CREATE TABLE dq.execucao (
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    executada_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    ocorrencias  integer NOT NULL DEFAULT 0
);

CREATE TABLE dq.ocorrencia (
    execucao_id integer NOT NULL REFERENCES dq.execucao (id),
    regra       text NOT NULL REFERENCES dq.regra (codigo),
    referencia  text NOT NULL,
    detalhe     text NOT NULL
);
CREATE INDEX ix_ocorrencia_execucao ON dq.ocorrencia (execucao_id, regra);
"""

CHECAGENS = r"""
-- DQ01: estado atual diferente do que o histórico reconstrói.
CREATE VIEW dq.chk_estado_divergente AS
SELECT item || ' ' || referencia_id AS referencia,
       'atual: ' || estado_atual || ' | pelo histórico: ' || estado_pelo_historico AS detalhe
FROM core.vw_divergencia_estado;

-- DQ02: saldo encadeado quebrado. Em cada material de consumo, o saldo_antes de uma
-- movimentação tem de ser o saldo_depois da anterior. A soma pode continuar certa e o
-- histórico estar errado (ex.: duas retiradas simultâneas sem trava registram o mesmo
-- saldo_antes), por isso a DQ01 não basta.
CREATE VIEW dq.chk_saldo_encadeamento AS
WITH ordem AS (
    SELECT id, material_tipo_id, saldo_antes,
           lag(saldo_depois) OVER (PARTITION BY material_tipo_id ORDER BY ocorrida_em, id)
               AS depois_da_anterior
    FROM core.movimentacao
    WHERE controle = 'CONSUMO'
)
SELECT 'movimentacao ' || id AS referencia,
       format('material %s: saldo_antes %s, mas a anterior terminou em %s',
              material_tipo_id, saldo_antes, coalesce(depois_da_anterior::text, 'nada (1a)'))
           AS detalhe
FROM ordem
WHERE saldo_antes IS DISTINCT FROM coalesce(depois_da_anterior, 0);

-- DQ03: situação encadeada quebrada. Em cada unidade, o status_anterior de uma
-- movimentação tem de ser o status_novo da anterior.
CREATE VIEW dq.chk_status_encadeamento AS
WITH ordem AS (
    SELECT id, unidade_id, status_anterior,
           lag(status_novo) OVER (PARTITION BY unidade_id ORDER BY ocorrida_em, id)
               AS status_da_anterior
    FROM core.movimentacao
    WHERE controle = 'SERIAL'
)
SELECT 'movimentacao ' || id AS referencia,
       format('unidade %s: status_anterior %s, mas a anterior deixou %s',
              unidade_id, coalesce(status_anterior, '-'), coalesce(status_da_anterior, '-'))
           AS detalhe
FROM ordem
WHERE status_anterior IS DISTINCT FROM status_da_anterior;

-- DQ04: unidade cautelada a quem já saiu da unidade (material que provavelmente foi
-- junto e que o inventário não vai achar).
CREATE VIEW dq.chk_cautela_com_transferido AS
SELECT 'unidade ' || u.id AS referencia,
       format('BMP %s cautelado a %s (matrícula %s), que saiu em %s',
              coalesce(u.bmp, '-'), p.nome, p.matricula, p.data_saida) AS detalhe
FROM core.unidade_patrimonial u
JOIN core.pessoa p ON p.id = u.detentor_id
WHERE u.status = 'CAUTELADA' AND p.data_saida IS NOT NULL;

-- DQ05: movimentação de retirada para pessoa fora do seu período na unidade.
CREATE VIEW dq.chk_pessoa_fora_do_periodo AS
SELECT 'movimentacao ' || m.id AS referencia,
       format('%s em %s para %s (na unidade de %s a %s)',
              m.tipo, core.data_local(m.ocorrida_em), p.matricula, p.data_entrada,
              coalesce(p.data_saida::text, 'hoje')) AS detalhe
FROM core.movimentacao m
JOIN core.pessoa p ON p.id = m.pessoa_id
WHERE m.tipo = 'RETIRADA'
  AND (core.data_local(m.ocorrida_em) < p.data_entrada
       OR core.data_local(m.ocorrida_em) >= p.data_saida);

-- DQ06: operação lançada por um perfil que não poderia fazê-la (hoje). O perfil pode
-- ter mudado depois do lançamento; a checagem aponta para revisão.
CREATE VIEW dq.chk_perfil_incompativel AS
SELECT 'movimentacao ' || m.id AS referencia,
       format('%s lançada por %s (perfil %s)', m.tipo, us.login, us.perfil) AS detalhe
FROM core.movimentacao m
JOIN core.usuario us ON us.id = m.executado_por
WHERE (m.tipo IN ('ENTRADA', 'AJUSTE', 'MUDANCA_STATUS')
           AND us.perfil NOT IN ('ADMINISTRADOR', 'ESTOQUISTA'))
   OR (m.tipo = 'ESTORNO' AND us.perfil <> 'ADMINISTRADOR')
   OR (m.tipo IN ('RETIRADA', 'DEVOLUCAO') AND us.perfil = 'CONSULTA');

-- DQ07: unidade sem a movimentação de entrada (entrou na carga por fora do processo).
CREATE VIEW dq.chk_unidade_sem_entrada AS
SELECT 'unidade ' || u.id AS referencia,
       format('BMP %s sem movimentação de ENTRADA', coalesce(u.bmp, '-')) AS detalhe
FROM core.unidade_patrimonial u
WHERE NOT EXISTS (
    SELECT 1 FROM core.movimentacao m WHERE m.unidade_id = u.id AND m.tipo = 'ENTRADA'
);

-- DQ08: material ativo cadastrado sem nenhuma unidade (serial) nem saldo (consumo).
CREATE VIEW dq.chk_material_orfao AS
SELECT 'material ' || t.codigo AS referencia,
       format('%s (%s) sem %s', t.nome, t.controle,
              CASE t.controle WHEN 'SERIAL' THEN 'unidades' ELSE 'saldo cadastrado' END)
           AS detalhe
FROM core.material_tipo t
WHERE t.ativo
  AND NOT EXISTS (SELECT 1 FROM core.unidade_patrimonial u WHERE u.material_tipo_id = t.id)
  AND NOT EXISTS (SELECT 1 FROM core.saldo_consumo s WHERE s.material_tipo_id = t.id);

-- DQ09: planilha (staging) com BMP fora do formato de 7 dígitos.
CREATE VIEW dq.chk_planilha_bmp_formato AS
SELECT 'planilha linha ' || linha AS referencia,
       format('BMP %L fora do formato de 7 dígitos', bmp) AS detalhe
FROM staging.carga_planilha
WHERE bmp IS NOT NULL AND bmp !~ '^[0-9]{7}$';

-- DQ10: planilha (staging) sem nomenclatura ou sem local.
CREATE VIEW dq.chk_planilha_campo_vazio AS
SELECT 'planilha linha ' || linha AS referencia,
       concat_ws(', ',
                 CASE WHEN nullif(btrim(nomenclatura), '') IS NULL THEN 'sem nomenclatura' END,
                 CASE WHEN nullif(btrim(local), '') IS NULL THEN 'sem local' END) AS detalhe
FROM staging.carga_planilha
WHERE nullif(btrim(nomenclatura), '') IS NULL OR nullif(btrim(local), '') IS NULL;

INSERT INTO dq.regra (codigo, descricao, severidade, visao) VALUES
    ('DQ01', 'Estado atual diferente do histórico', 'CRITICA', 'chk_estado_divergente'),
    ('DQ02', 'Saldo encadeado quebrado no histórico', 'CRITICA', 'chk_saldo_encadeamento'),
    ('DQ03', 'Situação encadeada quebrada no histórico', 'CRITICA', 'chk_status_encadeamento'),
    ('DQ04', 'Unidade cautelada a pessoa transferida', 'ALTA', 'chk_cautela_com_transferido'),
    ('DQ05', 'Retirada para pessoa fora do seu período', 'ALTA', 'chk_pessoa_fora_do_periodo'),
    ('DQ06', 'Operação lançada por perfil incompatível', 'ALTA', 'chk_perfil_incompativel'),
    ('DQ07', 'Unidade sem movimentação de entrada', 'CRITICA', 'chk_unidade_sem_entrada'),
    ('DQ08', 'Material ativo sem unidades nem saldo', 'MEDIA', 'chk_material_orfao'),
    ('DQ09', 'Planilha com BMP fora do formato', 'MEDIA', 'chk_planilha_bmp_formato'),
    ('DQ10', 'Planilha sem nomenclatura ou local', 'MEDIA', 'chk_planilha_campo_vazio');
"""

EXECUTAR = r"""
-- Roda todas as regras e grava as ocorrências. Devolve o id da execução.
-- O nome da view vem da tabela dq.regra, validado por CHECK (^chk_[a-z_]+$) e citado
-- com %I no format(): o SQL dinâmico não aceita injeção.
CREATE FUNCTION dq.executar() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_execucao integer;
    v_regra    dq.regra%ROWTYPE;
    v_total    integer := 0;
    v_linhas   integer;
BEGIN
    INSERT INTO dq.execucao DEFAULT VALUES RETURNING id INTO v_execucao;
    FOR v_regra IN SELECT * FROM dq.regra ORDER BY codigo LOOP
        EXECUTE format(
            'INSERT INTO dq.ocorrencia (execucao_id, regra, referencia, detalhe) '
            'SELECT $1, $2, referencia, detalhe FROM dq.%I', v_regra.visao)
        USING v_execucao, v_regra.codigo;
        GET DIAGNOSTICS v_linhas = ROW_COUNT;
        v_total := v_total + v_linhas;
    END LOOP;
    UPDATE dq.execucao SET ocorrencias = v_total WHERE id = v_execucao;
    RETURN v_execucao;
END;
$$;

-- Resumo da última execução: uma linha por regra, inclusive as sem ocorrência.
CREATE VIEW dq.vw_ultima_execucao AS
WITH ultima AS (SELECT max(id) AS id FROM dq.execucao)
SELECT r.codigo, r.descricao, r.severidade,
       count(o.regra) AS ocorrencias,
       (SELECT executada_em FROM dq.execucao WHERE id = u.id) AS executada_em
FROM dq.regra r
CROSS JOIN ultima u
LEFT JOIN dq.ocorrencia o ON o.regra = r.codigo AND o.execucao_id = u.id
GROUP BY r.codigo, r.descricao, r.severidade, u.id
ORDER BY r.codigo;
"""


def upgrade() -> None:
    op.execute(ESTRUTURA)
    op.execute(CHECAGENS)
    op.execute(EXECUTAR)


def downgrade() -> None:
    op.execute("DROP SCHEMA dq CASCADE;")
