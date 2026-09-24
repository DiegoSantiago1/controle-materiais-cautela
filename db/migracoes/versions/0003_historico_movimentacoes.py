"""histórico de movimentações (ledger imutável)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23

Toda mudança de estoque ou de situação de uma unidade vira uma linha aqui, e nenhuma
linha é alterada ou apagada depois. Um erro se corrige com um ESTORNO, que aponta
para a movimentação original. É isso que permite reconstruir o histórico completo
(quem, quando, o quê, saldo antes e depois) e auditar o estado atual.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE core.movimentacao (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            -- Quando o fato aconteceu (informado) e quando foi lançado (relógio do banco).
            ocorrida_em      timestamptz NOT NULL,
            lancada_em       timestamptz NOT NULL DEFAULT clock_timestamp(),
            tipo             text NOT NULL CONSTRAINT ck_mov_tipo CHECK (tipo IN (
                                 'ENTRADA', 'RETIRADA', 'DEVOLUCAO', 'MUDANCA_STATUS',
                                 'AJUSTE', 'ESTORNO'
                             )),
            material_tipo_id integer NOT NULL,
            controle         text NOT NULL
                             CONSTRAINT ck_mov_controle CHECK (controle IN ('SERIAL', 'CONSUMO')),

            -- Material SERIAL: a unidade e a mudança de situação.
            unidade_id       integer,
            status_anterior  text,
            status_novo      text,

            -- Material de CONSUMO: variação assinada e saldo antes/depois.
            variacao         integer,
            saldo_antes      integer,
            saldo_depois     integer,

            -- Quem recebe/devolve (ou, numa unidade que some, com quem ela estava).
            pessoa_id        integer REFERENCES core.pessoa (id),
            -- Quem lançou a movimentação no sistema.
            executado_por    integer NOT NULL REFERENCES core.usuario (id),
            setor_destino_id integer REFERENCES core.setor (id),
            finalidade       text CONSTRAINT ck_mov_finalidade CHECK (length(finalidade) <= 120),
            documento_ref    text CONSTRAINT ck_mov_documento CHECK (length(documento_ref) <= 40),
            prazo_devolucao  timestamptz,
            estado_devolucao text CONSTRAINT ck_mov_estado CHECK (
                                 estado_devolucao IN ('BOM', 'AVARIADO', 'INSERVIVEL')
                             ),
            observacao       text CONSTRAINT ck_mov_observacao CHECK (length(observacao) <= 500),
            estorno_de_id    bigint UNIQUE,

            CONSTRAINT fk_mov_material FOREIGN KEY (material_tipo_id, controle)
                REFERENCES core.material_tipo (id, controle),
            -- A unidade precisa ser do mesmo tipo de material informado.
            CONSTRAINT fk_mov_unidade FOREIGN KEY (unidade_id, material_tipo_id)
                REFERENCES core.unidade_patrimonial (id, material_tipo_id),
            -- O estorno aponta para uma movimentação do mesmo material.
            CONSTRAINT uq_mov_id_material UNIQUE (id, material_tipo_id),
            CONSTRAINT fk_mov_estorno FOREIGN KEY (estorno_de_id, material_tipo_id)
                REFERENCES core.movimentacao (id, material_tipo_id),

            -- Não se lança um fato do futuro (tolerância de 5 min para relógios).
            CONSTRAINT ck_mov_nao_futura CHECK (ocorrida_em <= lancada_em + interval '5 minutes'),

            -- Forma de cada controle: ou é serial, ou é consumo, nunca uma mistura.
            CONSTRAINT ck_mov_forma CHECK (
                (controle = 'SERIAL'
                    AND unidade_id IS NOT NULL
                    AND status_novo IS NOT NULL
                    AND variacao IS NULL AND saldo_antes IS NULL AND saldo_depois IS NULL)
                OR
                (controle = 'CONSUMO'
                    AND unidade_id IS NULL
                    AND status_anterior IS NULL AND status_novo IS NULL
                    AND variacao IS NOT NULL AND variacao <> 0
                    AND saldo_antes >= 0
                    AND saldo_depois >= 0
                    AND saldo_depois = saldo_antes + variacao)
            ),
            CONSTRAINT ck_mov_tipo_por_controle CHECK (
                (controle = 'SERIAL'
                    AND tipo IN ('ENTRADA', 'RETIRADA', 'DEVOLUCAO', 'MUDANCA_STATUS', 'ESTORNO'))
                OR
                (controle = 'CONSUMO' AND tipo IN ('ENTRADA', 'RETIRADA', 'AJUSTE', 'ESTORNO'))
            ),
            -- Sinal da variação coerente com o tipo (consumo).
            CONSTRAINT ck_mov_sinal CHECK (
                controle = 'SERIAL'
                OR (tipo = 'ENTRADA' AND variacao > 0)
                OR (tipo = 'RETIRADA' AND variacao < 0)
                OR tipo IN ('AJUSTE', 'ESTORNO')
            ),
            CONSTRAINT ck_mov_status_validos CHECK (
                (status_anterior IS NULL OR status_anterior IN (
                    'DISPONIVEL', 'CAUTELADA', 'EM_MANUTENCAO', 'NAO_LOCALIZADA',
                    'BAIXA_PENDENTE', 'BAIXADA', 'AGUARDANDO_TOMBAMENTO'))
                AND (status_novo IS NULL OR status_novo IN (
                    'DISPONIVEL', 'CAUTELADA', 'EM_MANUTENCAO', 'NAO_LOCALIZADA',
                    'BAIXA_PENDENTE', 'BAIXADA', 'AGUARDANDO_TOMBAMENTO'))
            ),
            -- Serial: só a ENTRADA não tem status anterior (a unidade nasce nela).
            CONSTRAINT ck_mov_status_anterior CHECK (
                controle = 'CONSUMO' OR (tipo = 'ENTRADA') = (status_anterior IS NULL)
            ),
            -- Retirada e devolução sempre identificam a pessoa.
            CONSTRAINT ck_mov_pessoa_obrigatoria CHECK (
                tipo NOT IN ('RETIRADA', 'DEVOLUCAO') OR pessoa_id IS NOT NULL
            ),
            -- Unidade cautelada sempre registra com quem ficou (permite reconstruir
            -- o detentor atual só pelo histórico).
            CONSTRAINT ck_mov_cautela_tem_pessoa CHECK (
                status_novo IS DISTINCT FROM 'CAUTELADA' OR pessoa_id IS NOT NULL
            ),
            CONSTRAINT ck_mov_prazo CHECK (
                prazo_devolucao IS NULL
                OR (tipo = 'RETIRADA' AND controle = 'SERIAL' AND prazo_devolucao > ocorrida_em)
            ),
            CONSTRAINT ck_mov_estado_so_devolucao CHECK (
                estado_devolucao IS NULL OR tipo = 'DEVOLUCAO'
            ),
            CONSTRAINT ck_mov_estorno CHECK ((tipo = 'ESTORNO') = (estorno_de_id IS NOT NULL)),
            CONSTRAINT ck_mov_estorno_nao_si_mesmo CHECK (estorno_de_id <> id)
        );

        COMMENT ON TABLE core.movimentacao IS
            'Histórico imutável: só INSERT. Correções são feitas com tipo ESTORNO.';

        -- Índices para os acessos previstos: linha do tempo de uma unidade (LAG/LEAD
        -- das cautelas), de um material, de uma pessoa, e filtro por período.
        CREATE INDEX ix_mov_unidade_tempo  ON core.movimentacao (unidade_id, ocorrida_em, id)
            WHERE unidade_id IS NOT NULL;
        CREATE INDEX ix_mov_material_tempo ON core.movimentacao (material_tipo_id, ocorrida_em, id);
        CREATE INDEX ix_mov_pessoa_tempo   ON core.movimentacao (pessoa_id, ocorrida_em)
            WHERE pessoa_id IS NOT NULL;
        CREATE INDEX ix_mov_tempo          ON core.movimentacao (ocorrida_em);

        -- Imutabilidade. Trigger de linha para UPDATE/DELETE e de comando para
        -- TRUNCATE (que não dispara triggers de linha).
        CREATE FUNCTION core.tg_historico_imutavel() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'O histórico de movimentações é imutável (% bloqueado). '
                            'Para corrigir um lançamento, registre um estorno.', TG_OP
                USING ERRCODE = 'ALM12';
        END;
        $$;

        CREATE TRIGGER tg_movimentacao_sem_update_delete
            BEFORE UPDATE OR DELETE ON core.movimentacao
            FOR EACH ROW EXECUTE FUNCTION core.tg_historico_imutavel();
        CREATE TRIGGER tg_movimentacao_sem_truncate
            BEFORE TRUNCATE ON core.movimentacao
            FOR EACH STATEMENT EXECUTE FUNCTION core.tg_historico_imutavel();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE core.movimentacao;
        DROP FUNCTION core.tg_historico_imutavel();
        """
    )
