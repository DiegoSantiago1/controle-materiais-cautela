"""schema core e tabelas de cadastro

Revision ID: 0001
Revises:
Create Date: 2026-09-23

Cadastros: categoria, subcategoria, setor, local de armazenagem, pessoa, usuário e
tipo de material (o catálogo). As tabelas de estado (unidade patrimonial, saldo) e o
histórico de movimentações vêm nas migrações seguintes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE SCHEMA core;
        COMMENT ON SCHEMA core IS
            'Dados limpos: integridade garantida pelo banco (FKs, CHECKs, UNIQUE).';

        -- Texto de nome: não vazio, sem espaço em branco nas pontas (espaço, TAB,
        -- quebra de linha), sem espaços duplos e sem caracteres de controle.
        -- Um domain é um tipo com regras; reutilizado em todas as colunas de nome.
        -- Ataca na origem o problema de nomenclatura das planilhas de carga
        -- ('Rádio  Portátil ', 'Rádio Portátil' e 'rádio portátil' como coisas diferentes).
        -- (btrim() não serviria: ele só remove o caractere espaço, não TAB.)
        CREATE DOMAIN core.nome AS text
            CONSTRAINT ck_nome_formato CHECK (
                VALUE <> ''
                AND VALUE !~ '^\s|\s$'
                AND VALUE !~ '\s{2,}'
                AND VALUE !~ '[[:cntrl:]]'
                AND length(VALUE) <= 120
            );

        CREATE TABLE core.categoria (
            id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nome core.nome NOT NULL
        );
        -- lower(): 'Ferramentas' e 'FERRAMENTAS' são a mesma categoria.
        CREATE UNIQUE INDEX uq_categoria_nome ON core.categoria (lower(nome));

        CREATE TABLE core.subcategoria (
            id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            categoria_id integer NOT NULL REFERENCES core.categoria (id),
            nome         core.nome NOT NULL
        );
        CREATE UNIQUE INDEX uq_subcategoria_nome ON core.subcategoria (categoria_id, lower(nome));

        CREATE TABLE core.setor (
            id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            sigla text NOT NULL UNIQUE CONSTRAINT ck_setor_sigla CHECK (sigla ~ '^[A-Z]{2,8}$'),
            nome  core.nome NOT NULL
        );
        CREATE UNIQUE INDEX uq_setor_nome ON core.setor (lower(nome));

        -- Locais genéricos (ex.: 'Depósito Central', 'Reserva de Equipamentos').
        -- Uma tabela, e não texto livre: a planilha real tinha o mesmo local
        -- escrito de cinco jeitos diferentes.
        CREATE TABLE core.local_armazenagem (
            id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nome core.nome NOT NULL
        );
        CREATE UNIQUE INDEX uq_local_nome ON core.local_armazenagem (lower(nome));

        -- Pessoa: quem recebe ou devolve material. Não precisa ter login.
        -- data_saida: transferência para outra unidade. Uma cautela aberta com
        -- alguém que já saiu é o caso clássico de material 'não localizado'.
        CREATE TABLE core.pessoa (
            id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            matricula     text NOT NULL UNIQUE
                          CONSTRAINT ck_pessoa_matricula CHECK (matricula ~ '^[0-9]{7}$'),
            nome          core.nome NOT NULL,
            setor_id      integer NOT NULL REFERENCES core.setor (id),
            data_entrada  date NOT NULL,
            data_saida    date,
            CONSTRAINT ck_pessoa_periodo CHECK (data_saida IS NULL OR data_saida >= data_entrada)
        );
        CREATE INDEX ix_pessoa_setor ON core.pessoa (setor_id);

        -- Usuário do sistema: uma pessoa com perfil de acesso. A autenticação
        -- (hash de senha, sessões) entra na fase da aplicação.
        CREATE TABLE core.usuario (
            id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            pessoa_id integer NOT NULL UNIQUE REFERENCES core.pessoa (id),
            login     text NOT NULL UNIQUE
                      CONSTRAINT ck_usuario_login CHECK (login ~ '^[a-z][a-z0-9._]{2,31}$'),
            perfil    text NOT NULL CONSTRAINT ck_usuario_perfil CHECK (
                          perfil IN ('ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA', 'CONSULTA')
                      ),
            ativo     boolean NOT NULL DEFAULT true
        );

        -- Catálogo: o TIPO de material. controle define como ele é controlado:
        --   SERIAL  -> cada unidade física tem número de patrimônio (BMP) e é
        --              rastreada individualmente (rádio, ferramenta, móvel);
        --   CONSUMO -> controlado só por quantidade (papel, toner, limpeza).
        CREATE TABLE core.material_tipo (
            id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            codigo                text NOT NULL UNIQUE CONSTRAINT ck_material_codigo
                                  CHECK (codigo ~ '^[A-Z]{3}-[0-9]{4}$'),
            nome                  core.nome NOT NULL,
            descricao             text CONSTRAINT ck_material_descricao
                                  CHECK (length(descricao) <= 500),
            subcategoria_id       integer NOT NULL REFERENCES core.subcategoria (id),
            unidade_medida        text NOT NULL CONSTRAINT ck_material_unidade CHECK (
                                      unidade_medida IN ('UN', 'CX', 'PCT', 'RESMA', 'L', 'GL',
                                                         'KG', 'M', 'ROLO', 'PAR', 'FRASCO')
                                  ),
            controle              text NOT NULL CONSTRAINT ck_material_controle
                                  CHECK (controle IN ('SERIAL', 'CONSUMO')),
            -- Prazo padrão de devolução de uma cautela. NULL = não cautelável
            -- (ex.: armário: é patrimônio, mas não sai emprestado).
            prazo_devolucao_horas integer CONSTRAINT ck_material_prazo
                                  CHECK (prazo_devolucao_horas BETWEEN 1 AND 8760),
            -- Valor fictício, usado na curva ABC e no capital parado.
            custo_unitario        numeric(12, 2) NOT NULL
                                  CONSTRAINT ck_material_custo CHECK (custo_unitario >= 0),
            ativo                 boolean NOT NULL DEFAULT true,
            -- Alvo das FKs compostas: permite que outra tabela exija, pelo banco,
            -- que o material seja de um controle específico.
            CONSTRAINT uq_material_id_controle UNIQUE (id, controle),
            -- Só material patrimonial é cautelado; material serial se conta em unidades.
            CONSTRAINT ck_material_prazo_so_serial
                CHECK (controle = 'SERIAL' OR prazo_devolucao_horas IS NULL),
            CONSTRAINT ck_material_serial_em_unidades
                CHECK (controle = 'CONSUMO' OR unidade_medida = 'UN')
        );
        CREATE UNIQUE INDEX uq_material_nome ON core.material_tipo (lower(nome));
        CREATE INDEX ix_material_subcategoria ON core.material_tipo (subcategoria_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA core CASCADE;")
