"""Testes unitários da configuração (não precisam do banco)."""

import pytest

from almox.config import ConfigError, carregar_config_banco

ENV_VALIDO = {
    "ALMOX_DB_HOST": "localhost",
    "ALMOX_DB_PORT": "5432",
    "ALMOX_DB_NAME": "almoxarifado",
    "ALMOX_DB_NAME_TESTE": "almoxarifado_teste",
    "ALMOX_DB_USER": "almox",
    "ALMOX_DB_PASSWORD": "senha_de_teste",
}


def env_com(**alteracoes: str) -> dict[str, str]:
    return {**ENV_VALIDO, **alteracoes}


def test_config_valida_monta_url_do_psycopg() -> None:
    config = carregar_config_banco(ENV_VALIDO)
    url = config.url()
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database, url.username) == (
        "localhost",
        5432,
        "almoxarifado",
        "almox",
    )


def test_senha_nao_aparece_em_repr_nem_na_url_impressa() -> None:
    config = carregar_config_banco(ENV_VALIDO)
    assert "senha_de_teste" not in repr(config)
    assert "senha_de_teste" not in str(config.url())  # o SQLAlchemy mascara com ***


@pytest.mark.parametrize(
    "senha", ["p@ss:w/o#rd%", "aspa'simples", 'aspa"dupla', "ç ã ü", " espaço "]
)
def test_senha_com_caracteres_especiais_chega_intacta(senha: str) -> None:
    assert carregar_config_banco(env_com(ALMOX_DB_PASSWORD=senha)).url().password == senha


@pytest.mark.parametrize("variavel", list(ENV_VALIDO))
def test_variavel_ausente_gera_erro_claro(variavel: str) -> None:
    env = {k: v for k, v in ENV_VALIDO.items() if k != variavel}
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env)


@pytest.mark.parametrize("variavel", list(ENV_VALIDO))
def test_variavel_em_branco_gera_erro(variavel: str) -> None:
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env_com(**{variavel: "   "}))


@pytest.mark.parametrize("porta", ["abc", "0", "-1", "65536", "5432.0", "99999999999999999999"])
def test_porta_invalida(porta: str) -> None:
    with pytest.raises(ConfigError, match="ALMOX_DB_PORT"):
        carregar_config_banco(env_com(ALMOX_DB_PORT=porta))


@pytest.mark.parametrize(
    "nome",
    [
        "almox; DROP DATABASE vendas_honda",  # tentativa de injeção
        'almox"',
        "Almox",  # maiúscula exigiria aspas no SQL
        "1almox",
        "almox-x",
        "almox x",
        "a" * 64,  # acima do limite de 63 do PostgreSQL
    ],
)
@pytest.mark.parametrize("variavel", ["ALMOX_DB_NAME", "ALMOX_DB_NAME_TESTE", "ALMOX_DB_USER"])
def test_identificador_hostil_e_recusado(variavel: str, nome: str) -> None:
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env_com(**{variavel: nome}))


def test_banco_de_teste_igual_ao_principal_e_recusado() -> None:
    """Sem esta trava, rodar os testes apagaria o banco principal."""
    with pytest.raises(ConfigError, match="não pode ser igual"):
        carregar_config_banco(env_com(ALMOX_DB_NAME_TESTE="almoxarifado"))


def test_do_banco_de_teste_troca_so_o_nome_do_banco() -> None:
    config = carregar_config_banco(ENV_VALIDO)
    teste = config.do_banco_de_teste()
    assert teste.nome == "almoxarifado_teste"
    assert (teste.host, teste.porta, teste.usuario, teste.senha) == (
        config.host,
        config.porta,
        config.usuario,
        config.senha,
    )


def test_identificador_no_limite_de_63_e_aceito() -> None:
    assert carregar_config_banco(env_com(ALMOX_DB_USER="a" * 63)).usuario == "a" * 63
