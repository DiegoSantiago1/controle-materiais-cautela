"""schema staging: planilha de carga "suja" e gabarito dos erros

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23

A planilha de conferência de carga entra aqui exatamente como veio: tudo texto, sem
restrições. É o ponto de partida da análise de conferência (limpar, padronizar e
cruzar com o schema core). O gabarito diz, para cada linha, qual é a unidade correta
e quais erros foram injetados pelo gerador; com ele a análise mede o próprio acerto
(precisão e revocação).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA staging;
        COMMENT ON SCHEMA staging IS
            'Dados como vieram da origem (texto, sem restrições), antes da limpeza.';

        -- Uma linha por linha do arquivo. Nenhum CHECK de propósito: o erro precisa
        -- conseguir entrar para ser encontrado. A única chave é o número da linha.
        CREATE TABLE staging.carga_planilha (
            linha        integer PRIMARY KEY,
            bmp          text,
            nomenclatura text,
            numero_serie text,
            local        text,
            situacao     text,
            observacao   text,
            arquivo      text NOT NULL,
            importada_em timestamptz NOT NULL DEFAULT now()
        );

        -- Gabarito por linha: a unidade que a linha deveria representar.
        CREATE TABLE staging.gabarito_linha (
            linha            integer PRIMARY KEY,
            unidade_ref      text NOT NULL,
            bmp_correto      text,
            material_codigo  text NOT NULL,
            local_correto    text NOT NULL,
            -- Linha que é cópia de outra (a original).
            duplicata_de     integer
        );

        -- Gabarito por erro: cada erro injetado numa linha.
        CREATE TABLE staging.gabarito_erro (
            id                 integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            linha              integer NOT NULL,
            padrao             text NOT NULL,
            tipo_erro          text NOT NULL,
            campo              text,
            valor_na_planilha  text,
            valor_correto      text
        );
        CREATE INDEX ix_gabarito_erro_linha ON staging.gabarito_erro (linha);
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA staging CASCADE;")
