"""schema bi: modelo estrela para o Power BI e leitura com menor privilégio (V1)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-24

O Power BI conecta com um usuário SOMENTE LEITURA (grupo almox_leitura, criado pelo
bootstrap), que enxerga os schemas bi, analise e dq e nada mais: nem core nem staging.
As views leem o core com os direitos do dono delas, então o BI vê o resultado sem ter
acesso às tabelas.

Modelo estrela (o formato que o Power BI espera):
- dimensões: dim_calendario, dim_material, dim_pessoa, dim_setor;
- fatos: fato_movimentacao, fato_cautela, fato_consumo_diario.
Datas e horas vêm em horário local (sem fuso), para o Power BI não converter.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = r"""
CREATE SCHEMA bi;
COMMENT ON SCHEMA bi IS 'Modelo estrela para o Power BI (somente leitura).';

-- Tabela de datas: um dia por linha, nos 12 meses até a data de referência.
CREATE VIEW bi.dim_calendario AS
WITH ref AS (SELECT core.data_local(analise.momento_referencia()) AS ultimo_dia)
SELECT d::date                                  AS data,
       extract(year FROM d)::int                AS ano,
       extract(month FROM d)::int               AS mes,
       to_char(d, 'YYYY-MM')                    AS ano_mes,
       extract(quarter FROM d)::int             AS trimestre,
       extract(isodow FROM d)::int              AS dia_da_semana,  -- 1 = segunda
       extract(isodow FROM d) < 6               AS dia_util
FROM ref, generate_series(ref.ultimo_dia - 364, ref.ultimo_dia, interval '1 day') AS d;

CREATE VIEW bi.dim_setor AS
SELECT sigla, nome FROM core.setor;

CREATE VIEW bi.dim_pessoa AS
SELECT p.matricula, p.nome, s.sigla AS setor, p.data_entrada, p.data_saida,
       p.data_saida IS NULL AS na_unidade
FROM core.pessoa p
JOIN core.setor s ON s.id = p.setor_id;

CREATE VIEW bi.dim_material AS
SELECT t.codigo, t.nome, c.nome AS categoria, s.nome AS subcategoria, t.controle,
       t.unidade_medida, t.prazo_devolucao_horas, t.custo_unitario, t.ativo
FROM core.material_tipo t
JOIN core.subcategoria s ON s.id = t.subcategoria_id
JOIN core.categoria c ON c.id = s.categoria_id;

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

CREATE VIEW bi.fato_cautela AS
SELECT retirada_id,
       core.data_local(retirada_em)                   AS data_retirada,
       (retirada_em AT TIME ZONE 'America/Recife')    AS retirada_em,
       (prazo AT TIME ZONE 'America/Recife')          AS prazo,
       (devolvida_em AT TIME ZONE 'America/Recife')   AS devolvida_em,
       material, bmp, matricula AS pessoa, setor, situacao, atrasada,
       dias_de_atraso, horas_com_a_pessoa, mesmo_dia, estado_na_devolucao
FROM analise.vw_cautela;

CREATE VIEW bi.fato_consumo_diario AS
SELECT dia AS data, codigo AS material, saida, saldo_fim_do_dia,
       estoque_minimo, estoque_maximo,
       saldo_fim_do_dia = 0 AS zerado
FROM analise.vw_consumo_diario;
"""

PERMISSOES = r"""
-- Views rodam com os direitos do DONO; funções chamadas dentro delas, com os de QUEM
-- CONSULTA (SECURITY INVOKER, o padrão). Por isso:
-- 1. momento_referencia() passa a SECURITY DEFINER: devolve um único número (o instante
--    da última movimentação), então rodar com os direitos do dono é seguro. search_path
--    fixo evita que alguém "sequestre" um nome com um objeto próprio.
--    E, sem nenhuma movimentação ainda (banco novo), a referência passa a ser "agora":
--    antes devolvia NULL e todas as views com período (calendário, cautelas, consumo)
--    ficavam vazias sem explicação.
CREATE OR REPLACE FUNCTION analise.momento_referencia() RETURNS timestamptz
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT coalesce(max(ocorrida_em), now()) FROM core.movimentacao
$$;

-- 2. Por padrão QUALQUER usuário pode executar qualquer função (EXECUTE para PUBLIC).
--    As funções de escrita do core (registrar_*, estornar...) ficam só com o dono.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA core FROM PUBLIC;
-- ...e as funções que forem criadas no core no futuro também.
ALTER DEFAULT PRIVILEGES IN SCHEMA core REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- 3. Grupo de leitura do Power BI (só se existir: o bootstrap o cria).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_leitura') THEN
        GRANT USAGE ON SCHEMA bi, analise, dq TO almox_leitura;
        GRANT SELECT ON ALL TABLES IN SCHEMA bi, analise, dq TO almox_leitura;
        -- Views criadas depois (novas análises) já nascem legíveis pelo grupo.
        ALTER DEFAULT PRIVILEGES IN SCHEMA bi, analise, dq
            GRANT SELECT ON TABLES TO almox_leitura;
        -- As views usam core.data_local() (conta pura de fuso). Só ela é liberada: USAGE
        -- no schema permite referenciar, mas nenhuma tabela nem outra função do core.
        GRANT USAGE ON SCHEMA core TO almox_leitura;
        GRANT EXECUTE ON FUNCTION core.data_local(timestamptz) TO almox_leitura;
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute(VIEWS)
    op.execute(PERMISSOES)


def downgrade() -> None:
    op.execute(
        r"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_leitura') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA bi, analise, dq
                    REVOKE SELECT ON TABLES FROM almox_leitura;
                REVOKE SELECT ON ALL TABLES IN SCHEMA analise, dq FROM almox_leitura;
                REVOKE USAGE ON SCHEMA analise, dq, core FROM almox_leitura;
                REVOKE EXECUTE ON FUNCTION core.data_local(timestamptz) FROM almox_leitura;
            END IF;
        END;
        $$;
        ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA core TO PUBLIC;
        CREATE OR REPLACE FUNCTION analise.momento_referencia() RETURNS timestamptz
        LANGUAGE sql STABLE SECURITY INVOKER AS $f$
            SELECT max(ocorrida_em) FROM core.movimentacao
        $f$;
        ALTER FUNCTION analise.momento_referencia() RESET search_path;
        DROP SCHEMA bi CASCADE;
        """
    )
