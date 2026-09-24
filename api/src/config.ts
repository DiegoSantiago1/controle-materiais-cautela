/**
 * Configuração da API, lida do mesmo .env da raiz do projeto (o do Python).
 *
 * Tudo que é segredo vem do ambiente. A validação acontece aqui, na borda: valor ausente
 * ou inválido para a API na partida com uma mensagem clara, e não num erro confuso do
 * driver depois.
 */
import path from "node:path";

export const RAIZ_PROJETO = path.resolve(import.meta.dirname, "..", "..");
export const PASTA_WEB = path.join(RAIZ_PROJETO, "web");

export class ErroDeConfiguracao extends Error {}

export interface ConfigBanco {
  host: string;
  porta: number;
  banco: string;
  usuario: string;
  senha: string;
}

export interface ConfigApi {
  /** Conexão da API: usuário da aplicação (menor privilégio), banco da aplicação. */
  banco: ConfigBanco;
  /** Dono do banco: só para scripts administrativos (definir senha) e para os testes. */
  dono: ConfigBanco;
  bancoDeTeste: string;
  portaHttp: number;
  /** Cookie com o atributo Secure (exige HTTPS). Desligado só para rodar em localhost. */
  cookieSeguro: boolean;
}

type Ambiente = Record<string, string | undefined>;

/** Carrega o .env da raiz, sem sobrescrever o que já está no ambiente do processo. */
export function carregarArquivoEnv(): void {
  try {
    process.loadEnvFile(path.join(RAIZ_PROJETO, ".env"));
  } catch (erro) {
    // Sem .env tudo bem, se as variáveis vierem do ambiente; a validação abaixo acusa a falta.
    if ((erro as NodeJS.ErrnoException).code !== "ENOENT") throw erro;
  }
}

function obrigatoria(env: Ambiente, nome: string): string {
  const valor = env[nome];
  if (valor === undefined || valor.trim() === "") {
    throw new ErroDeConfiguracao(
      `Variável ${nome} não definida. Copie .env.example para .env e preencha.`,
    );
  }
  return valor;
}

// Mesma regra do Python (almox/config.py): nomes que nunca exigem aspas no SQL.
const IDENTIFICADOR = /^[a-z_][a-z0-9_]{0,62}$/;

function identificador(env: Ambiente, nome: string): string {
  const valor = obrigatoria(env, nome);
  if (!IDENTIFICADOR.test(valor)) {
    throw new ErroDeConfiguracao(`${nome}=${JSON.stringify(valor)} inválido.`);
  }
  return valor;
}

function porta(texto: string, nome: string): number {
  if (!/^[0-9]{1,5}$/.test(texto) || Number(texto) < 1 || Number(texto) > 65535) {
    throw new ErroDeConfiguracao(`${nome}=${JSON.stringify(texto)} não é uma porta válida.`);
  }
  return Number(texto);
}

export function carregarConfig(env: Ambiente = process.env): ConfigApi {
  const host = obrigatoria(env, "ALMOX_DB_HOST");
  const portaBanco = porta(obrigatoria(env, "ALMOX_DB_PORT"), "ALMOX_DB_PORT");
  const bancoPrincipal = identificador(env, "ALMOX_DB_NAME");
  const bancoDeTeste = identificador(env, "ALMOX_DB_NAME_TESTE");
  const bancoApp = identificador(env, "ALMOX_DB_NAME_APP");
  // A aplicação nunca grava no banco das análises (mudaria os números dos notebooks).
  if (bancoApp === bancoPrincipal || bancoApp === bancoDeTeste) {
    throw new ErroDeConfiguracao(
      "ALMOX_DB_NAME_APP precisa ser diferente de ALMOX_DB_NAME e de ALMOX_DB_NAME_TESTE.",
    );
  }
  const usuarioApp = identificador(env, "ALMOX_APP_USER");
  const dono = identificador(env, "ALMOX_DB_USER");
  if (usuarioApp === dono) {
    throw new ErroDeConfiguracao("ALMOX_APP_USER não pode ser o dono do banco.");
  }

  const cookieSeguro = (env.ALMOX_API_COOKIE_SEGURO ?? "nao").toLowerCase();
  if (cookieSeguro !== "sim" && cookieSeguro !== "nao") {
    throw new ErroDeConfiguracao('ALMOX_API_COOKIE_SEGURO deve ser "sim" ou "nao".');
  }

  return {
    banco: {
      host,
      porta: portaBanco,
      banco: bancoApp,
      usuario: usuarioApp,
      senha: obrigatoria(env, "ALMOX_APP_PASSWORD"),
    },
    dono: {
      host,
      porta: portaBanco,
      banco: bancoApp,
      usuario: dono,
      senha: obrigatoria(env, "ALMOX_DB_PASSWORD"),
    },
    bancoDeTeste,
    portaHttp: porta(env.ALMOX_API_PORT ?? "3334", "ALMOX_API_PORT"),
    cookieSeguro: cookieSeguro === "sim",
  };
}
