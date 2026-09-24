"""aplicação: login, sessões e usuário da API com menor privilégio (P3.1)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-24

A API conecta com um usuário do grupo almox_aplicacao (criado pelo bootstrap), que:
- LÊ os cadastros, o estado atual e o histórico (para buscar e listar);
- EXECUTA só as duas funções de regra que a tela usa (retirada e devolução);
- NÃO tem INSERT, UPDATE nem DELETE em nenhuma tabela do core.

Para isso funcionar, as funções de escrita passam a SECURITY DEFINER: rodam com os
direitos do dono do banco, e não com os de quem chama. É o único caminho para o
histórico: mesmo com a API comprometida, um INSERT direto em core.movimentacao é
recusado pelo banco. search_path fixo (pg_catalog, pg_temp) impede que quem chama
"sequestre" um nome criando um objeto próprio; as funções já usam nomes qualificados
(core.xxx), o que foi conferido antes desta migração.

Schema app: credenciais (hash scrypt) e sessões (só o hash SHA-256 do token). Assim, um
vazamento do banco não entrega nem senhas nem sessões válidas.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Todas as funções públicas que gravam. Ficam todas SECURITY DEFINER (e não só as duas
# que a tela usa) para que a regra seja uma só: escrita no core só por função. Liberar
# uma nova operação para a API passa a ser só um GRANT EXECUTE.
FUNCOES_DE_ESCRITA = (
    "registrar_entrada_unidade",
    "registrar_retirada_unidade",
    "registrar_devolucao_unidade",
    "alterar_status_unidade",
    "cadastrar_saldo_consumo",
    "registrar_entrada_consumo",
    "registrar_retirada_consumo",
    "registrar_ajuste_consumo",
    "estornar_movimentacao",
)

SCHEMA_APP = r"""
CREATE SCHEMA app;
COMMENT ON SCHEMA app IS 'Login e sessões da aplicação do equipamentista.';

-- Uma senha por usuário. Formato: scrypt$N$r$p$sal$hash (sal e hash em base64url).
-- O CHECK garante que nunca se grava uma senha em texto puro por engano.
CREATE TABLE app.credencial (
    usuario_id    integer PRIMARY KEY REFERENCES core.usuario (id),
    senha_hash    text NOT NULL CONSTRAINT ck_credencial_formato CHECK (
        senha_hash ~ '^scrypt(\$[0-9]+){3}\$[A-Za-z0-9_-]{16,}\$[A-Za-z0-9_-]{32,}$'
    ),
    atualizada_em timestamptz NOT NULL DEFAULT now()
);

-- Sessão aberta no login. O navegador guarda o token (cookie HttpOnly); o banco guarda
-- só o SHA-256 dele (32 bytes). Quem lê esta tabela não consegue se passar pelo usuário.
CREATE TABLE app.sessao (
    token_hash bytea PRIMARY KEY CONSTRAINT ck_sessao_hash CHECK (octet_length(token_hash) = 32),
    usuario_id integer NOT NULL REFERENCES core.usuario (id),
    criada_em  timestamptz NOT NULL DEFAULT now(),
    expira_em  timestamptz NOT NULL,
    CONSTRAINT ck_sessao_validade CHECK (expira_em > criada_em)
);
CREATE INDEX ix_sessao_expira_em ON app.sessao (expira_em);
"""


def _definer() -> str:
    return "\n".join(
        f"ALTER FUNCTION core.{nome} SECURITY DEFINER SET search_path = pg_catalog, pg_temp;"
        for nome in FUNCOES_DE_ESCRITA
    )


def _invoker() -> str:
    return "\n".join(
        f"ALTER FUNCTION core.{nome} SECURITY INVOKER RESET search_path;"
        for nome in FUNCOES_DE_ESCRITA
    )


# O que a API lê: cadastros, estado atual e histórico (para buscar e listar). Nada de
# staging, analise, dq ou bi. Escrita: só app.sessao (login e logout).
PERMISSOES = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        GRANT USAGE ON SCHEMA core, app TO almox_aplicacao;
        GRANT SELECT ON core.categoria, core.subcategoria, core.setor,
                        core.local_armazenagem, core.pessoa, core.usuario,
                        core.material_tipo, core.unidade_patrimonial, core.movimentacao
            TO almox_aplicacao;
        GRANT EXECUTE ON FUNCTION core.registrar_retirada_unidade,
                                  core.registrar_devolucao_unidade,
                                  core.data_local
            TO almox_aplicacao;
        GRANT SELECT ON app.credencial TO almox_aplicacao;
        GRANT SELECT, INSERT, DELETE ON app.sessao TO almox_aplicacao;
    END IF;
END;
$$;
"""

REVOGAR = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        REVOKE SELECT ON core.categoria, core.subcategoria, core.setor,
                         core.local_armazenagem, core.pessoa, core.usuario,
                         core.material_tipo, core.unidade_patrimonial, core.movimentacao
            FROM almox_aplicacao;
        REVOKE EXECUTE ON FUNCTION core.registrar_retirada_unidade,
                                   core.registrar_devolucao_unidade,
                                   core.data_local
            FROM almox_aplicacao;
        REVOKE USAGE ON SCHEMA core FROM almox_aplicacao;
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute(SCHEMA_APP)
    op.execute(_definer())
    op.execute(PERMISSOES)


def downgrade() -> None:
    op.execute(REVOGAR)
    op.execute(_invoker())
    # CASCADE leva junto as permissões do grupo nas tabelas e no schema app.
    op.execute("DROP SCHEMA app CASCADE;")
