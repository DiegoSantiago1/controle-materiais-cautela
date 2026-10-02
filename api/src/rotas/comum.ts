/**
 * O que as rotas compartilham: dependências, quem está logado, controle de perfil e
 * transação.
 *
 * Toda escrita passa pelas funções app.* do banco, que recebem o hash do token da sessão
 * (migração 0015): é o banco que descobre quem está logado. O controle de perfil aqui na
 * API é a primeira barreira (resposta 403 rápida e clara); a segunda é a função do banco,
 * que confere o perfil de novo.
 */
import type { NextFunction, Request, Response } from "express";
import type pg from "pg";
import { ErroHttp } from "../erros.ts";
import type { LimiteDeTentativas } from "../limite.ts";
import type { UsuarioDaSessao } from "../sessao.ts";

export interface Dependencias {
  pool: pg.Pool;
  cookieSeguro: boolean;
  limitePorLogin: LimiteDeTentativas;
  limitePorIp: LimiteDeTentativas;
}

export type Perfil = "ADMINISTRADOR" | "ESTOQUISTA" | "EQUIPAMENTISTA" | "CONSULTA";

/** Quem atende no balcão (retirada e devolução). */
export const OPERACIONAIS: readonly Perfil[] = ["ADMINISTRADOR", "ESTOQUISTA", "EQUIPAMENTISTA"];
/** Quem dá entrada em material e faz ajuste de estoque. */
export const GESTAO_DE_ESTOQUE: readonly Perfil[] = ["ADMINISTRADOR", "ESTOQUISTA"];
/** Cadastros, usuários e permissões. */
export const ADMINISTRACAO: readonly Perfil[] = ["ADMINISTRADOR"];

export function usuario(res: Response): UsuarioDaSessao {
  return res.locals.usuario as UsuarioDaSessao;
}

/** Hash do token da sessão: o primeiro parâmetro de toda função app.* do banco. */
export function sessao(res: Response): Buffer {
  return res.locals.tokenHash as Buffer;
}

export function exigirPerfil(perfis: readonly Perfil[]) {
  return (_req: Request, res: Response, next: NextFunction): void => {
    if (!perfis.includes(usuario(res).perfil as Perfil)) {
      throw new ErroHttp(403, "Seu perfil não tem acesso a esta função.", "SEM_PERMISSAO");
    }
    next();
  };
}

/** Executa tudo numa transação: ou entra tudo (COMMIT), ou nada (ROLLBACK). */
export async function emTransacao<T>(
  pool: pg.Pool,
  trabalho: (cliente: pg.PoolClient) => Promise<T>,
): Promise<T> {
  const cliente = await pool.connect();
  try {
    await cliente.query("BEGIN");
    const resultado = await trabalho(cliente);
    await cliente.query("COMMIT");
    return resultado;
  } catch (erro) {
    await cliente.query("ROLLBACK").catch(() => undefined);
    throw erro;
  } finally {
    cliente.release();
  }
}

const ID_NA_ROTA = /^[1-9][0-9]{0,9}$/;
const INT_MAX = 2_147_483_647;

/** Id que vem na URL (/materiais/42). Qualquer outra coisa é "não encontrado". */
export function idDaRota(req: Request, nome = "id"): number {
  const texto = req.params[nome];
  const numero = Number(texto);
  if (typeof texto !== "string" || !ID_NA_ROTA.test(texto) || numero > INT_MAX) {
    throw new ErroHttp(404, "Registro não encontrado.", "NAO_ENCONTRADO");
  }
  return numero;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function uuid(valor: unknown): string {
  if (typeof valor !== "string" || !UUID.test(valor)) {
    throw new ErroHttp(404, "Operação não encontrada.", "NAO_ENCONTRADO");
  }
  return valor;
}

// Busca sem acento e sem diferença de maiúsculas: "radio" encontra "Rádio". translate()
// é nativo do PostgreSQL; a extensão unaccent está no schema analise, que a API não lê.
export const SEM_ACENTO = (expressao: string): string =>
  `translate(lower(${expressao}), 'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc')`;
