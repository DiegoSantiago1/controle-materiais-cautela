"""posto/graduação e nome de guerra dos militares

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-24

Posto e graduação (tabela de referência, com a ordem hierárquica) e nome de guerra de cada
pessoa. É como o militar é chamado no dia a dia ("SGT Souza"), e é por ele que o
equipamentista procura quem está no balcão. O nome de guerra é único entre quem está na
unidade (índice parcial): dois "Souza" no mesmo balcão gerariam cautela no nome errado.

A lista de postos segue a pedida pelo dono do projeto (siglas genéricas, comuns às três
Forças): S2, S1, CB, SGT, ST, TEN, CAP, MAJ, TEN-CEL e CEL. "ST" é o subtenente (a lista
original trazia "ST" e "SUBTEN", que são o mesmo posto).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTOS = r"""
-- Do mais moderno ao mais antigo. A ordem serve para listar por hierarquia.
CREATE TABLE core.posto_graduacao (
    sigla   text PRIMARY KEY
            CONSTRAINT ck_posto_sigla CHECK (sigla ~ '^[A-Z0-9]{2,3}(-[A-Z]{3})?$'),
    nome    text NOT NULL UNIQUE,
    circulo text NOT NULL CONSTRAINT ck_posto_circulo CHECK (
                circulo IN ('PRACAS', 'SUBTENENTES E SARGENTOS', 'OFICIAIS')
            ),
    ordem   smallint NOT NULL UNIQUE
);

INSERT INTO core.posto_graduacao (sigla, nome, circulo, ordem) VALUES
    ('S2',      'Soldado de Segunda Classe',  'PRACAS', 1),
    ('S1',      'Soldado de Primeira Classe', 'PRACAS', 2),
    ('CB',      'Cabo',                       'PRACAS', 3),
    ('SGT',     'Sargento',                   'SUBTENENTES E SARGENTOS', 4),
    ('ST',      'Subtenente',                 'SUBTENENTES E SARGENTOS', 5),
    ('TEN',     'Tenente',                    'OFICIAIS', 6),
    ('CAP',     'Capitão',                    'OFICIAIS', 7),
    ('MAJ',     'Major',                      'OFICIAIS', 8),
    ('TEN-CEL', 'Tenente-Coronel',            'OFICIAIS', 9),
    ('CEL',     'Coronel',                    'OFICIAIS', 10);

ALTER TABLE core.pessoa
    ADD COLUMN posto_graduacao text REFERENCES core.posto_graduacao (sigla),
    ADD COLUMN nome_guerra core.nome
        CONSTRAINT ck_pessoa_nome_guerra CHECK (length(nome_guerra) <= 30);

-- Só para linhas que já existissem antes desta migração (a carga informa os valores
-- reais). O id no fim garante que o índice único abaixo não falhe.
UPDATE core.pessoa
SET posto_graduacao = 'S2',
    nome_guerra = left(split_part(nome, ' ', 1), 20) || ' ' || id
WHERE posto_graduacao IS NULL;

ALTER TABLE core.pessoa
    ALTER COLUMN posto_graduacao SET NOT NULL,
    ALTER COLUMN nome_guerra SET NOT NULL;

-- Nome de guerra único entre quem está na unidade (quem já saiu pode ter o mesmo de
-- alguém que chegou depois). lower(): "Souza" e "SOUZA" são o mesmo nome.
CREATE UNIQUE INDEX uq_pessoa_nome_guerra_ativo
    ON core.pessoa (lower(nome_guerra)) WHERE data_saida IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        GRANT SELECT ON core.posto_graduacao TO almox_aplicacao;
    END IF;
END;
$$;
"""

# O Power BI passa a ver posto e nome de guerra (colunas novas no fim da view).
DIM_PESSOA = r"""
CREATE OR REPLACE VIEW bi.dim_pessoa AS
SELECT p.matricula, p.nome, s.sigla AS setor, p.data_entrada, p.data_saida,
       p.data_saida IS NULL AS na_unidade,
       p.posto_graduacao, pg.nome AS posto_graduacao_nome, pg.ordem AS posto_ordem,
       p.nome_guerra
FROM core.pessoa p
JOIN core.setor s ON s.id = p.setor_id
JOIN core.posto_graduacao pg ON pg.sigla = p.posto_graduacao;
"""

DIM_PESSOA_ANTIGA = r"""
DROP VIEW bi.dim_pessoa;
CREATE VIEW bi.dim_pessoa AS
SELECT p.matricula, p.nome, s.sigla AS setor, p.data_entrada, p.data_saida,
       p.data_saida IS NULL AS na_unidade
FROM core.pessoa p
JOIN core.setor s ON s.id = p.setor_id;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_leitura') THEN
        GRANT SELECT ON bi.dim_pessoa TO almox_leitura;
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute(POSTOS)
    op.execute(DIM_PESSOA)


def downgrade() -> None:
    op.execute(DIM_PESSOA_ANTIGA)
    op.execute(
        """
        DROP INDEX core.uq_pessoa_nome_guerra_ativo;
        ALTER TABLE core.pessoa DROP COLUMN nome_guerra, DROP COLUMN posto_graduacao;
        DROP TABLE core.posto_graduacao;
        """
    )
