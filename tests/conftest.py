"""Fixtures compartilhadas pelos testes.

Testes marcados com @pytest.mark.integracao precisam do Docker e do banco. Se o banco
não estiver acessível eles FALHAM com uma mensagem clara, em vez de serem pulados em
silêncio: um teste pulado sem ninguém ver é um teste que não existe.
Para rodar só os unitários: pytest -m "not integracao".

Os testes de schema e de regras usam o banco de TESTES (ALMOX_DB_NAME_TESTE), que é
apagado e recriado pelas migrações no início de cada execução. O banco principal só é
lido, pelos testes de bootstrap (test_banco.py).
"""

import os
import shutil
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from dotenv import load_dotenv

from almox.banco import Conexao, conectar
from almox.config import RAIZ_PROJETO, ConfigBanco, ConfigError, carregar_config_banco
from almox.migracoes import config_alembic

from .apoio import valor
from .cenario import Base, criar_base

load_dotenv(RAIZ_PROJETO / ".env", override=False)


def _falhar_sem_banco(erro: Exception) -> None:
    pytest.fail(
        f"Banco inacessível ({erro}). Docker Desktop aberto? Já rodou 'python -m almox.bootstrap'?",
        pytrace=False,
    )


@pytest.fixture(scope="session")
def config_banco() -> ConfigBanco:
    try:
        return carregar_config_banco()
    except ConfigError as erro:
        pytest.fail(f"Configuração do banco inválida: {erro}", pytrace=False)


@pytest.fixture
def conexao(config_banco: ConfigBanco) -> Iterator[Conexao]:
    """Conexão ao banco PRINCIPAL, como o usuário do projeto. Tudo é desfeito (ROLLBACK)."""
    try:
        con = conectar(config_banco)
    except psycopg.OperationalError as erro:
        _falhar_sem_banco(erro)
    try:
        yield con
    finally:
        con.rollback()
        con.close()


@pytest.fixture(scope="session")
def banco_teste(config_banco: ConfigBanco) -> ConfigBanco:
    """Banco de testes recriado do zero pelas migrações.

    Sobe tudo, desce tudo (confere que não sobrou nada) e sobe de novo: cada execução
    dos testes também exercita os downgrades.
    """
    config = config_banco.do_banco_de_teste()
    assert config.nome != config_banco.nome  # trava extra: nunca recriar o principal
    alembic = config_alembic(config.url())
    try:
        command.upgrade(alembic, "head")
        command.downgrade(alembic, "base")
        with conectar(config) as con:
            sobrou = valor(con, "SELECT count(*) FROM pg_namespace WHERE nspname = 'core'")
        assert sobrou == 0, "downgrade base deixou o schema core para trás"
        command.upgrade(alembic, "head")
    except psycopg.OperationalError as erro:
        _falhar_sem_banco(erro)
    return config


@pytest.fixture(scope="session")
def base(banco_teste: ConfigBanco) -> Base:
    """Cadastros mínimos, confirmados (COMMIT) no banco de testes."""
    with conectar(banco_teste) as con:
        return criar_base(con)  # o `with` faz COMMIT ao sair sem erro


@pytest.fixture
def bd(banco_teste: ConfigBanco, base: Base) -> Iterator[Conexao]:
    """Conexão ao banco de testes dentro de uma transação desfeita no fim do teste."""
    con = conectar(banco_teste)
    con.execute("SELECT 1")  # abre a transação: blocos internos viram savepoints
    try:
        yield con
    finally:
        con.rollback()
        con.close()


@pytest.fixture(scope="session")
def psql_superusuario() -> list[str]:
    """Comando base para rodar o psql como superusuário dentro do container."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Comando 'docker' não encontrado.", pytrace=False)
    container = os.environ.get("ALMOX_DOCKER_CONTAINER", "")
    superusuario = os.environ.get("ALMOX_DOCKER_SUPERUSER", "")
    if not container or not superusuario:
        pytest.fail(
            "Defina ALMOX_DOCKER_CONTAINER e ALMOX_DOCKER_SUPERUSER no .env.", pytrace=False
        )
    return [docker, "exec", "-i", container,
            "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
            "-U", superusuario, "-d", "postgres"]  # fmt: skip
