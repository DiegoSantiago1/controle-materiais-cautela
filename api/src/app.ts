/**
 * Montagem do servidor: cabeçalhos de segurança, proteção contra CSRF, arquivos da tela,
 * rotas da API e tratamento de erros. Recebe o pool pronto (os testes passam o do banco
 * de testes).
 */
import express, { type NextFunction, type Request, type Response } from "express";
import type pg from "pg";
import { PASTA_WEB } from "./config.ts";
import { ErroHttp, traduzirErroDoBanco } from "./erros.ts";
import { LimiteDeTentativas } from "./limite.ts";
import { criarRotas } from "./rotas.ts";

export interface OpcoesApp {
  pool: pg.Pool;
  cookieSeguro: boolean;
  /** Os testes usam um limite próprio para não depender do relógio real. */
  limitePorLogin?: LimiteDeTentativas;
  limitePorIp?: LimiteDeTentativas;
}

const QUINZE_MINUTOS = 15 * 60 * 1000;

/**
 * Content-Security-Policy: o navegador só executa script e estilo vindos deste mesmo
 * servidor, nada inline. Se um texto malicioso escapasse para a página (XSS), o script
 * injetado não rodaria. É a segunda camada; a primeira é a tela nunca montar HTML com
 * dados (usa textContent).
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
].join("; ");

function cabecalhosDeSeguranca(_req: Request, res: Response, next: NextFunction): void {
  res.setHeader("Content-Security-Policy", CSP);
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  next();
}

/**
 * Contra CSRF, além do cookie SameSite=Strict: todo pedido que altera algo precisa vir
 * como JSON (um formulário de outro site não consegue mandar Content-Type JSON sem o
 * navegador pedir permissão antes) e, se o navegador informar a origem, ela tem de ser
 * este mesmo servidor.
 */
function exigirMesmaOrigemEJson(req: Request, _res: Response, next: NextFunction): void {
  if (req.method === "GET" || req.method === "HEAD") {
    next();
    return;
  }
  const origem = req.headers.origin;
  if (origem !== undefined && origem !== `${req.protocol}://${req.headers.host}`) {
    throw new ErroHttp(403, "Origem do pedido não permitida.", "ORIGEM_PROIBIDA");
  }
  const temCorpo =
    req.headers["content-length"] !== undefined && req.headers["content-length"] !== "0";
  if ((req.method === "POST" || temCorpo) && !req.is("application/json")) {
    throw new ErroHttp(415, "Envie o pedido como JSON.", "FORMATO_NAO_SUPORTADO");
  }
  next();
}

function tratarErros(erro: unknown, req: Request, res: Response, _next: NextFunction): void {
  // Erros do leitor de JSON do Express (corpo inválido ou grande demais).
  const tipo = (erro as { type?: string }).type;
  if (tipo === "entity.parse.failed") {
    res.status(400).json({ erro: "JSON inválido.", codigo: "PEDIDO_INVALIDO" });
    return;
  }
  if (tipo === "entity.too.large") {
    res.status(413).json({ erro: "Pedido grande demais.", codigo: "PEDIDO_GRANDE" });
    return;
  }
  const conhecido = erro instanceof ErroHttp ? erro : traduzirErroDoBanco(erro);
  if (conhecido !== undefined) {
    const campo = (conhecido as { campo?: string }).campo;
    res.status(conhecido.status).json({
      erro: conhecido.message,
      codigo: conhecido.codigo,
      ...(campo === undefined ? {} : { campo }),
    });
    return;
  }
  // Inesperado: detalhe só no log do servidor; para o cliente, mensagem genérica.
  console.error(`[erro] ${req.method} ${req.path}:`, erro);
  res.status(500).json({ erro: "Erro interno. Tente de novo.", codigo: "ERRO_INTERNO" });
}

export function criarApp(opcoes: OpcoesApp): express.Express {
  const app = express();
  app.disable("x-powered-by");

  app.use(cabecalhosDeSeguranca);
  app.use(express.static(PASTA_WEB, { index: "index.html", dotfiles: "deny" }));

  const api = express.Router();
  api.use((_req, res, next) => {
    res.setHeader("Cache-Control", "no-store"); // dado de sessão nunca fica em cache
    next();
  });
  api.use(exigirMesmaOrigemEJson);
  api.use(express.json({ limit: "10kb" }));
  api.use(
    criarRotas({
      pool: opcoes.pool,
      cookieSeguro: opcoes.cookieSeguro,
      limitePorLogin: opcoes.limitePorLogin ?? new LimiteDeTentativas(5, QUINZE_MINUTOS),
      limitePorIp: opcoes.limitePorIp ?? new LimiteDeTentativas(20, QUINZE_MINUTOS),
    }),
  );
  app.use("/api", api);
  app.use("/api", (_req, res) => {
    res.status(404).json({ erro: "Rota não encontrada.", codigo: "NAO_ENCONTRADO" });
  });
  app.use(tratarErros);
  return app;
}
