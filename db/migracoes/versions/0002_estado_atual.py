"""estado atual: unidades patrimoniais e saldo de consumo

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

Estas tabelas guardam o estado ATUAL (onde está cada unidade, quanto há de cada
material de consumo). A fonte da verdade é o histórico de movimentações (0003); o
estado é atualizado na mesma transação que grava cada movimentação (0004), e um teste
confere que os dois nunca divergem.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        -- Cada linha é UMA unidade física de material permanente.
        CREATE TABLE core.unidade_patrimonial (
            id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            material_tipo_id integer NOT NULL,
            -- Coluna fixa em 'SERIAL' só para a FK composta abaixo: o banco recusa
            -- uma unidade de um material de CONSUMO.
            controle         text NOT NULL DEFAULT 'SERIAL'
                             CONSTRAINT ck_unidade_controle CHECK (controle = 'SERIAL'),
            -- Número de patrimônio (fictício). Único; ausente só enquanto o material
            -- recém-adquirido aguarda tombamento.
            bmp              text UNIQUE CONSTRAINT ck_unidade_bmp CHECK (bmp ~ '^[0-9]{7}$'),
            numero_serie     text CONSTRAINT ck_unidade_serie CHECK (
                                 numero_serie !~ '^\s|\s$'
                                 AND numero_serie <> ''
                                 AND length(numero_serie) <= 40
                             ),
            local_id         integer NOT NULL REFERENCES core.local_armazenagem (id),
            status           text NOT NULL CONSTRAINT ck_unidade_status CHECK (status IN (
                                 'DISPONIVEL', 'CAUTELADA', 'EM_MANUTENCAO', 'NAO_LOCALIZADA',
                                 'BAIXA_PENDENTE', 'BAIXADA', 'AGUARDANDO_TOMBAMENTO'
                             )),
            -- Pessoa com quem a unidade está (só quando cautelada).
            detentor_id      integer REFERENCES core.pessoa (id),

            CONSTRAINT fk_unidade_material_serial FOREIGN KEY (material_tipo_id, controle)
                REFERENCES core.material_tipo (id, controle),
            -- Alvo da FK composta do histórico: a movimentação de uma unidade tem
            -- de citar o mesmo tipo de material da unidade.
            CONSTRAINT uq_unidade_id_material UNIQUE (id, material_tipo_id),
            -- Cautelada <=> tem detentor.
            CONSTRAINT ck_unidade_cautelada_tem_detentor
                CHECK ((status = 'CAUTELADA') = (detentor_id IS NOT NULL)),
            -- Sem BMP <=> aguardando tombamento.
            CONSTRAINT ck_unidade_sem_bmp_aguarda_tombamento
                CHECK ((bmp IS NULL) = (status = 'AGUARDANDO_TOMBAMENTO'))
        );
        -- O mesmo número de série não pode aparecer em duas unidades do mesmo tipo
        -- (erro real da planilha de carga). Índice parcial: muitas unidades não têm série.
        CREATE UNIQUE INDEX uq_unidade_serie
            ON core.unidade_patrimonial (material_tipo_id, numero_serie)
            WHERE numero_serie IS NOT NULL;
        CREATE INDEX ix_unidade_material ON core.unidade_patrimonial (material_tipo_id);
        CREATE INDEX ix_unidade_detentor ON core.unidade_patrimonial (detentor_id)
            WHERE detentor_id IS NOT NULL;

        -- Saldo de cada material de CONSUMO (uma linha por material).
        CREATE TABLE core.saldo_consumo (
            material_tipo_id integer PRIMARY KEY,
            controle         text NOT NULL DEFAULT 'CONSUMO'
                             CONSTRAINT ck_saldo_controle CHECK (controle = 'CONSUMO'),
            local_id         integer NOT NULL REFERENCES core.local_armazenagem (id),
            -- A última linha de defesa contra retirada acima do estoque: mesmo que
            -- algum código esqueça a validação, o banco recusa saldo negativo.
            quantidade       integer NOT NULL DEFAULT 0
                             CONSTRAINT ck_saldo_nao_negativo CHECK (quantidade >= 0),
            estoque_minimo   integer NOT NULL
                             CONSTRAINT ck_saldo_minimo CHECK (estoque_minimo >= 0),
            estoque_maximo   integer NOT NULL,

            CONSTRAINT fk_saldo_material_consumo FOREIGN KEY (material_tipo_id, controle)
                REFERENCES core.material_tipo (id, controle),
            CONSTRAINT ck_saldo_maximo
                CHECK (estoque_maximo > 0 AND estoque_maximo >= estoque_minimo)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE core.saldo_consumo;
        DROP TABLE core.unidade_patrimonial;
        """
    )
