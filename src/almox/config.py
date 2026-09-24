"""Configuração de acesso ao banco, lida de variáveis de ambiente (arquivo .env).

Tudo que é segredo (senha) vem do ambiente e nunca do código. A validação acontece
aqui, na borda: um valor ausente ou inválido gera um erro claro na hora de carregar,
e não um erro confuso lá dentro do driver do PostgreSQL.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

RAIZ_PROJETO = Path(__file__).resolve().parents[2]

# Nome de banco e de usuário: só minúsculas, dígitos e "_", começando por letra ou "_".
# Limite de 63 caracteres do PostgreSQL. Evita nomes que exigiriam aspas no SQL.
_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]{0,62}")


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class ConfigBanco:
    host: str
    porta: int
    nome: str
    usuario: str
    # repr=False: a senha não aparece se o objeto for impresso num log ou traceback.
    senha: str = field(repr=False)

    def url(self) -> URL:
        """URL do SQLAlchemy. URL.create trata caracteres especiais da senha sem escape manual."""
        return URL.create(
            "postgresql+psycopg",
            username=self.usuario,
            password=self.senha,
            host=self.host,
            port=self.porta,
            database=self.nome,
        )


def _obrigatoria(env: Mapping[str, str], nome: str) -> str:
    valor = env.get(nome)
    if valor is None or not valor.strip():
        raise ConfigError(f"Variável {nome} não definida. Copie .env.example para .env e preencha.")
    return valor


def validar_identificador(valor: str, nome_variavel: str) -> str:
    if not _IDENTIFICADOR.fullmatch(valor):
        raise ConfigError(
            f"{nome_variavel}={valor!r} inválido: use só letras minúsculas, dígitos e '_', "
            "começando por letra ou '_' (máx. 63 caracteres)."
        )
    return valor


def _porta(texto: str) -> int:
    try:
        porta = int(texto)
    except ValueError:
        raise ConfigError(f"ALMOX_DB_PORT={texto!r} não é um número.") from None
    if not 1 <= porta <= 65535:
        raise ConfigError(f"ALMOX_DB_PORT={porta} fora do intervalo 1-65535.")
    return porta


def carregar_config_banco(env: Mapping[str, str] | None = None) -> ConfigBanco:
    """Lê a configuração do banco.

    Sem argumento, usa o ambiente do processo mais o .env da raiz do projeto (variáveis
    já definidas no ambiente têm prioridade sobre o .env). Os testes passam um dicionário.
    """
    if env is None:
        load_dotenv(RAIZ_PROJETO / ".env", override=False)
        env = os.environ

    return ConfigBanco(
        host=_obrigatoria(env, "ALMOX_DB_HOST"),
        porta=_porta(_obrigatoria(env, "ALMOX_DB_PORT")),
        nome=validar_identificador(_obrigatoria(env, "ALMOX_DB_NAME"), "ALMOX_DB_NAME"),
        usuario=validar_identificador(_obrigatoria(env, "ALMOX_DB_USER"), "ALMOX_DB_USER"),
        senha=_obrigatoria(env, "ALMOX_DB_PASSWORD"),
    )
