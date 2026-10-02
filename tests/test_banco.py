"""Testes de integração do banco criado pelo bootstrap.

Verificam as garantias de segurança e configuração, conectando como o usuário do
projeto (o mesmo que as migrações e a aplicação vão usar).
"""

import psycopg
import pytest
from psycopg import errors

from almox.banco import Conexao, conectar
from almox.config import ConfigBanco

from .apoio import valor

pytestmark = pytest.mark.integracao

# Banco do Projeto 1, que divide o mesmo container.
BANCO_VIZINHO = "vendas_honda"


def test_conecta_como_usuario_do_projeto_no_banco_do_projeto(
    conexao: Conexao, config_banco: ConfigBanco
) -> None:
    assert valor(conexao, "SELECT current_user") == config_banco.usuario
    assert valor(conexao, "SELECT current_database()") == config_banco.nome


def test_fuso_do_banco_e_recife(conexao: Conexao) -> None:
    assert valor(conexao, "SHOW timezone") == "America/Recife"


def test_banco_usa_utf8(conexao: Conexao) -> None:
    assert valor(conexao, "SHOW server_encoding") == "UTF8"


def test_usuario_nao_tem_privilegios_de_servidor(conexao: Conexao) -> None:
    linha = conexao.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert linha == (False, False, False, False, False)


def test_usuario_nao_consegue_criar_role(conexao: Conexao) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        conexao.execute("CREATE ROLE intruso LOGIN")


def test_usuario_nao_consegue_criar_banco(config_banco: ConfigBanco) -> None:
    # CREATE DATABASE não roda dentro de transação: precisa de autocommit.
    with conectar(config_banco) as con:
        con.autocommit = True
        with pytest.raises(errors.InsufficientPrivilege):
            con.execute("CREATE DATABASE intruso")


def test_somente_o_dono_e_a_leitura_podem_conectar(
    conexao: Conexao, config_banco: ConfigBanco
) -> None:
    # aclexplode abre a lista de permissões; grantee = 0 representa o PUBLIC (todo mundo).
    linhas = conexao.execute(
        """
        SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END
        FROM pg_database d, aclexplode(d.datacl) a
        WHERE d.datname = current_database() AND a.privilege_type = 'CONNECT'
        """
    ).fetchall()
    # O dono e o grupo somente leitura do Power BI; ninguém mais (nem PUBLIC).
    assert sorted(linhas) == sorted([(config_banco.usuario,), ("almox_leitura",)])


def test_usuario_nao_le_dados_do_projeto_1(config_banco: ConfigBanco) -> None:
    """O PostgreSQL deixa qualquer role CONECTAR no banco vizinho por padrão (a configuração
    do Projeto 1 não foi alterada), mas o usuário deste projeto não pode LER nenhuma tabela
    ou view de lá."""
    try:
        con = conectar(config_banco, banco=BANCO_VIZINHO)
    except psycopg.OperationalError:
        return  # não conseguir nem conectar também é isolamento
    with con:
        legiveis = con.execute(
            """
            SELECT count(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND has_table_privilege(c.oid, 'SELECT')
            """
        ).fetchone()
        total = con.execute(
            """
            SELECT count(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            """
        ).fetchone()
    assert total is not None and total[0] > 0, "banco vizinho sem tabelas: teste não prova nada"
    assert legiveis == (0,)


def test_senha_errada_e_recusada(config_banco: ConfigBanco) -> None:
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        psycopg.connect(
            host=config_banco.host,
            port=config_banco.porta,
            dbname=config_banco.nome,
            user=config_banco.usuario,
            password=config_banco.senha + "_errada",
            connect_timeout=5,
        )


def test_banco_da_aplicacao_so_aceita_o_dono_a_api_e_a_leitura(config_banco: ConfigBanco) -> None:
    """No banco da aplicação conectam o dono, a API e o grupo de leitura do Power BI (o
    relatório operacional, D27); a API não conecta no das análises (test_aplicacao.py)."""
    with conectar(config_banco.do_banco_da_aplicacao()) as con:
        linhas = con.execute(
            """
            SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END
            FROM pg_database d, aclexplode(d.datacl) a
            WHERE d.datname = current_database() AND a.privilege_type = 'CONNECT'
            """
        ).fetchall()
    assert sorted(linhas) == sorted(
        [(config_banco.usuario,), ("almox_aplicacao",), ("almox_leitura",)]
    )
