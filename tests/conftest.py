"""Fixtures compartilhadas pelos testes.

Testes marcados com @pytest.mark.integracao precisam do Docker e do banco. Se o banco
não estiver acessível eles FALHAM com uma mensagem clara, em vez de serem pulados em
silêncio: um teste pulado sem ninguém ver é um teste que não existe.
Para rodar só os unitários: pytest -m "not integracao".
"""

import os
import shutil
from collections.abc import Iterator

import psycopg
import pytest
from dotenv import load_dotenv

from almox.config import RAIZ_PROJETO, ConfigBanco, ConfigError, carregar_config_banco

from .apoio import Conexao, conectar

load_dotenv(RAIZ_PROJETO / ".env", override=False)


@pytest.fixture(scope="session")
def config_banco() -> ConfigBanco:
    try:
        return carregar_config_banco()
    except ConfigError as erro:
        pytest.fail(f"Configuração do banco inválida: {erro}", pytrace=False)


@pytest.fixture
def conexao(config_banco: ConfigBanco) -> Iterator[Conexao]:
    """Conexão como o usuário do projeto. Tudo que o teste fizer é desfeito (ROLLBACK)."""
    try:
        con = conectar(config_banco)
    except psycopg.OperationalError as erro:
        pytest.fail(
            f"Banco inacessível ({erro}). Docker Desktop aberto? Já rodou "
            "'python -m almox.bootstrap'?",
            pytrace=False,
        )
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
