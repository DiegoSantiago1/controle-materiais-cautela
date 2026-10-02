/**
 * Sessões: o login gera um token aleatório de 32 bytes que vai para o navegador num
 * cookie HttpOnly; o banco guarda só o SHA-256 dele.
 *
 * - HttpOnly: o JavaScript da página não lê o cookie, então um XSS não rouba a sessão.
 * - SameSite=Strict: o navegador não manda o cookie em pedidos iniciados por outro site,
 *   o que bloqueia CSRF (um site malicioso disparando uma retirada em nome do usuário).
 * - Hash no banco: quem ler a tabela de sessões não consegue se passar por ninguém. Aqui
 *   basta SHA-256 (e não scrypt) porque o token é aleatório, com 256 bits: não há
 *   dicionário para testar, ao contrário de uma senha escolhida por uma pessoa.
 */
import { createHash, randomBytes } from "node:crypto";
import type { Request } from "express";
import type pg from "pg";

export const NOME_DO_COOKIE = "almox_sessao";
export const DURACAO_MS = 8 * 60 * 60 * 1000; // um turno de trabalho

export interface UsuarioDaSessao {
  id: number;
  login: string;
  perfil: string;
  nome: string;
  posto: string;
  nome_guerra: string;
}

const TOKEN = /^[A-Za-z0-9_-]{43}$/; // 32 bytes em base64url, sem preenchimento

/** O banco guarda e as funções app.* recebem só este hash, nunca o token. */
export function hashDoToken(token: string): Buffer {
  return createHash("sha256").update(token).digest();
}

export async function abrirSessao(pool: pg.Pool, usuarioId: number): Promise<string> {
  const token = randomBytes(32).toString("base64url");
  // Aproveita o login para apagar sessões vencidas: a tabela não cresce para sempre.
  await pool.query("DELETE FROM app.sessao WHERE expira_em <= now()");
  await pool.query(
    `INSERT INTO app.sessao (token_hash, usuario_id, expira_em)
     VALUES ($1, $2, now() + make_interval(secs => $3))`,
    [hashDoToken(token), usuarioId, DURACAO_MS / 1000],
  );
  return token;
}

export async function buscarSessao(
  pool: pg.Pool,
  token: string | undefined,
): Promise<UsuarioDaSessao | undefined> {
  if (token === undefined || !TOKEN.test(token)) return undefined;
  // Usuário desativado perde o acesso na hora, mesmo com sessão aberta.
  const { rows } = await pool.query<UsuarioDaSessao>(
    `SELECT u.id, u.login, u.perfil, p.nome, p.posto_graduacao AS posto, p.nome_guerra
     FROM app.sessao s
     JOIN core.usuario u ON u.id = s.usuario_id
     JOIN core.pessoa p ON p.id = u.pessoa_id
     WHERE s.token_hash = $1 AND s.expira_em > now() AND u.ativo`,
    [hashDoToken(token)],
  );
  return rows[0];
}

export async function encerrarSessao(pool: pg.Pool, token: string | undefined): Promise<void> {
  if (token === undefined || !TOKEN.test(token)) return;
  await pool.query("DELETE FROM app.sessao WHERE token_hash = $1", [hashDoToken(token)]);
}

/** Lê o token do cabeçalho Cookie (sem dependência: o formato é simples). */
export function tokenDoPedido(req: Request): string | undefined {
  const cabecalho = req.headers.cookie;
  if (cabecalho === undefined) return undefined;
  for (const parte of cabecalho.split(";")) {
    const [nome, ...resto] = parte.trim().split("=");
    if (nome === NOME_DO_COOKIE) return resto.join("=");
  }
  return undefined;
}
