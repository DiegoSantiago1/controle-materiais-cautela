"""Testes do bootstrap: citação de valores para o psql e montagem do comando.

A citação é a parte delicada: se estiver errada, uma senha com aspa ou barra
invertida chega alterada ao banco (ou quebra o script). Por isso, além dos testes
unitários, há um teste de integração que passa os valores pelo psql de verdade.
"""

import subprocess

import pytest

from almox.bootstrap import citar_valor_psql, comando_psql, montar_entrada_psql
from almox.config import ConfigBanco, ConfigError

VALORES_DIFICEIS = [
    "simples",
    "it's",
    "duas''aspas",
    "barra\\invertida",
    "\\n literal",
    "fim com barra\\",
    ":'senha'",  # parece uma variável do psql
    "%L %I %s",  # parece marcador do format()
    "'; DROP ROLE almox; --",
    "ç ã ü €",
]


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("abc", "'abc'"),
        ("it's", "'it''s'"),
        ("a\\b", "'a\\\\b'"),
    ],
)
def test_citacao_escapa_aspa_e_barra(valor: str, esperado: str) -> None:
    assert citar_valor_psql(valor) == esperado


@pytest.mark.parametrize("valor", ["linha\nnova", "retorno\r", "nulo\0"])
def test_citacao_recusa_quebra_de_linha_e_nulo(valor: str) -> None:
    with pytest.raises(ConfigError):
        citar_valor_psql(valor)


def test_entrada_define_as_variaveis_antes_do_sql() -> None:
    config = ConfigBanco(
        host="127.0.0.1",
        porta=5432,
        nome="almoxarifado",
        usuario="almox",
        nome_teste="almoxarifado_teste",
        usuario_bi="almox_bi",
        nome_app="almoxarifado_app",
        usuario_app="almox_api",
        senha="s3nha",
        senha_bi="s3nha_bi",
        senha_app="s3nha_app",
    )
    entrada = montar_entrada_psql(config, "SELECT 1;")
    linhas = entrada.splitlines()
    assert linhas[:4] == [
        "\\set usuario 'almox'",
        "\\set senha 's3nha'",
        "\\set banco 'almoxarifado'",
        "\\set banco_teste 'almoxarifado_teste'",
    ]
    assert "\\set bi_usuario 'almox_bi'" in linhas
    assert "\\set bi_senha 's3nha_bi'" in linhas
    assert "\\set banco_app 'almoxarifado_app'" in linhas
    assert "\\set app_usuario 'almox_api'" in linhas
    assert "\\set app_senha 's3nha_app'" in linhas
    assert entrada.endswith("SELECT 1;")


def test_linha_de_comando_nao_contem_a_senha() -> None:
    comando = comando_psql("docker", "honda-vendas-db", "honda")
    assert "s3nha" not in " ".join(comando)
    assert comando[:4] == ["docker", "exec", "-i", "honda-vendas-db"]
    assert "ON_ERROR_STOP=1" in comando


@pytest.mark.integracao
@pytest.mark.parametrize("valor", VALORES_DIFICEIS)
def test_valor_citado_chega_intacto_ao_psql_real(valor: str, psql_superusuario: list[str]) -> None:
    """Envia \\set + SELECT :'x' ao psql do container e confere o valor devolvido."""
    entrada = f"\\set x {citar_valor_psql(valor)}\nSELECT :'x' AS x;\n"
    resultado = subprocess.run(  # noqa: S603 (comando fixo, sem shell)
        psql_superusuario,
        input=entrada.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    assert resultado.stdout.decode("utf-8").removesuffix("\n") == valor
