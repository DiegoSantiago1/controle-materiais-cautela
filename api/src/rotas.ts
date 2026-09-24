/**
 * Rotas da API. Todo SQL é escrito à mão e parametrizado ($1, $2...): o valor do usuário
 * nunca é colado no texto da consulta, então não há como injetar SQL.
 *
 * Escrita só pelas funções de regra do banco (core.registrar_*). O usuário do banco que a
 * API usa não tem INSERT, UPDATE nem DELETE em nenhuma tabela do core (migração 0012).
 */
import { type NextFunction, type Request, type Response, Router } from "express";
import type pg from "pg";
import { ErroHttp } from "./erros.ts";
import type { LimiteDeTentativas } from "./limite.ts";
import { conferirSenha, gastarTempoDeConferencia, SENHA_MAX } from "./senha.ts";
import {
  abrirSessao,
  buscarSessao,
  DURACAO_MS,
  encerrarSessao,
  NOME_DO_COOKIE,
  tokenDoPedido,
  type UsuarioDaSessao,
} from "./sessao.ts";
import * as v from "./validacao.ts";

export interface Dependencias {
  pool: pg.Pool;
  cookieSeguro: boolean;
  limitePorLogin: LimiteDeTentativas;
  limitePorIp: LimiteDeTentativas;
}

const ESTADOS_DE_DEVOLUCAO = ["BOM", "AVARIADO", "INSERVIVEL"] as const;

// Busca sem acento e sem diferença de maiúsculas: "radio" encontra "Rádio". translate()
// é nativo do PostgreSQL; a extensão unaccent está no schema analise, que a API não lê.
const SEM_ACENTO = (coluna: string) =>
  `translate(lower(${coluna}), 'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc')`;

function usuario(res: Response): UsuarioDaSessao {
  return res.locals.usuario as UsuarioDaSessao;
}

export function criarRotas(dep: Dependencias): Router {
  const { pool } = dep;
  const rotas = Router();

  // ---------------------------------------------------------------- sessão
  rotas.post("/sessao", async (req, res) => {
    const corpo = v.objeto(req.body);
    const login = v.texto(corpo.login, "login", 32).toLowerCase();
    const senha = corpo.senha;
    if (typeof senha !== "string" || senha.length === 0 || senha.length > SENHA_MAX) {
      throw new v.ErroDeValidacao("senha", "Informe a senha.");
    }

    const ip = req.socket.remoteAddress ?? "desconhecido";
    const espera = Math.max(
      dep.limitePorLogin.segundosBloqueado(login),
      dep.limitePorIp.segundosBloqueado(ip),
    );
    if (espera > 0) {
      res.setHeader("Retry-After", String(espera));
      throw new ErroHttp(429, "Muitas tentativas. Aguarde alguns minutos.", "MUITAS_TENTATIVAS");
    }

    const { rows } = await pool.query<{ id: number; senha_hash: string }>(
      `SELECT u.id, c.senha_hash
       FROM core.usuario u
       JOIN app.credencial c ON c.usuario_id = u.id
       WHERE u.login = $1 AND u.ativo`,
      [login],
    );
    const encontrado = rows[0];
    let confere = false;
    if (encontrado === undefined) {
      await gastarTempoDeConferencia(senha);
    } else {
      confere = await conferirSenha(senha, encontrado.senha_hash);
    }

    if (encontrado === undefined || !confere) {
      dep.limitePorLogin.registrarFalha(login);
      dep.limitePorIp.registrarFalha(ip);
      // A mesma mensagem para login inexistente e senha errada: não revela quem existe.
      throw new ErroHttp(401, "Login ou senha inválidos.", "CREDENCIAIS_INVALIDAS");
    }

    dep.limitePorLogin.limpar(login);
    const token = await abrirSessao(pool, encontrado.id);
    res.cookie(NOME_DO_COOKIE, token, {
      httpOnly: true,
      sameSite: "strict",
      secure: dep.cookieSeguro,
      maxAge: DURACAO_MS,
      path: "/",
    });
    res.json({ usuario: await buscarSessao(pool, token) });
  });

  // "Quem sou eu?": sem sessão, a resposta é usuario null (200), e não um erro. A tela
  // pergunta isso ao abrir; um 401 aqui apareceria como erro no console a cada visita.
  rotas.get("/sessao", async (req, res) => {
    res.json({ usuario: (await buscarSessao(pool, tokenDoPedido(req))) ?? null });
  });

  rotas.delete("/sessao", async (req, res) => {
    await encerrarSessao(pool, tokenDoPedido(req));
    res.clearCookie(NOME_DO_COOKIE, { path: "/", httpOnly: true, sameSite: "strict" });
    res.status(204).end();
  });

  // Daqui para baixo, tudo exige sessão válida.
  rotas.use(async (req: Request, res: Response, next: NextFunction) => {
    const encontrado = await buscarSessao(pool, tokenDoPedido(req));
    if (encontrado === undefined) {
      throw new ErroHttp(401, "Sessão expirada. Entre de novo.", "SEM_SESSAO");
    }
    res.locals.usuario = encontrado;
    next();
  });

  // ---------------------------------------------------------------- consultas
  /** Unidades cauteláveis por BMP, número de série ou nome do material. */
  rotas.get("/unidades", async (req, res) => {
    const termo = v.termoDeBusca(req.query.busca);
    const { rows } = await pool.query(
      `SELECT u.id, u.bmp, u.numero_serie, u.status, t.codigo, t.nome AS material,
              t.prazo_devolucao_horas, p.nome AS detentor
       FROM core.unidade_patrimonial u
       JOIN core.material_tipo t ON t.id = u.material_tipo_id
       LEFT JOIN core.pessoa p ON p.id = u.detentor_id
       WHERE t.prazo_devolucao_horas IS NOT NULL
         AND (u.bmp = $1
              OR u.numero_serie ILIKE $2 ESCAPE '\\'
              OR ${SEM_ACENTO("t.nome")} LIKE ${SEM_ACENTO("$3")} ESCAPE '\\')
       ORDER BY u.status = 'DISPONIVEL' DESC, t.nome, u.bmp NULLS LAST
       LIMIT 20`,
      [termo, `${v.escaparLike(termo)}%`, `%${v.escaparLike(termo)}%`],
    );
    res.json({ unidades: rows });
  });

  /** Pessoas que estão na unidade hoje, por nome ou matrícula. */
  rotas.get("/pessoas", async (req, res) => {
    const termo = v.termoDeBusca(req.query.busca);
    const { rows } = await pool.query(
      `SELECT p.id, p.nome, p.matricula, s.sigla AS setor
       FROM core.pessoa p
       JOIN core.setor s ON s.id = p.setor_id
       WHERE p.data_entrada <= core.data_local(now())
         AND (p.data_saida IS NULL OR p.data_saida > core.data_local(now()))
         AND (p.matricula LIKE $1 ESCAPE '\\'
              OR ${SEM_ACENTO("p.nome")} LIKE ${SEM_ACENTO("$2")} ESCAPE '\\')
       ORDER BY p.nome
       LIMIT 20`,
      [`${v.escaparLike(termo)}%`, `%${v.escaparLike(termo)}%`],
    );
    res.json({ pessoas: rows });
  });

  /**
   * Cautelas em aberto: unidades CAUTELADAS e a retirada que as abriu (a mais recente).
   * As vencidas vêm primeiro (ordem pelo prazo).
   */
  rotas.get("/cautelas", async (_req, res) => {
    const { rows } = await pool.query(
      `SELECT u.id AS unidade_id, u.bmp, u.numero_serie, t.codigo, t.nome AS material,
              p.id AS pessoa_id, p.nome AS pessoa, p.matricula, s.sigla AS setor,
              r.ocorrida_em AS retirada_em, r.prazo_devolucao AS prazo,
              r.prazo_devolucao < now() AS vencida
       FROM core.unidade_patrimonial u
       JOIN core.material_tipo t ON t.id = u.material_tipo_id
       JOIN core.pessoa p ON p.id = u.detentor_id
       JOIN core.setor s ON s.id = p.setor_id
       JOIN LATERAL (
           SELECT m.ocorrida_em, m.prazo_devolucao
           FROM core.movimentacao m
           WHERE m.unidade_id = u.id AND m.tipo = 'RETIRADA'
           ORDER BY m.ocorrida_em DESC, m.id DESC
           LIMIT 1
       ) r ON true
       WHERE u.status = 'CAUTELADA'
       ORDER BY r.prazo_devolucao, u.id`,
    );
    res.json({ cautelas: rows });
  });

  // ---------------------------------------------------------------- movimentações
  /** Retirada (abre uma cautela). Quem executa vem da sessão, nunca do corpo do pedido. */
  rotas.post("/retiradas", async (req, res) => {
    const corpo = v.objeto(req.body);
    const unidadeId = v.id(corpo.unidade_id, "unidade_id");
    const pessoaId = v.id(corpo.pessoa_id, "pessoa_id");
    const finalidade = v.textoOpcional(corpo.finalidade, "finalidade", 200);

    const { rows } = await pool.query<{ id: number }>(
      `SELECT core.registrar_retirada_unidade(
           p_unidade_id => $1, p_pessoa_id => $2, p_executado_por => $3,
           p_finalidade => $4) AS id`,
      [unidadeId, pessoaId, usuario(res).id, finalidade],
    );
    const movimentacaoId = rows[0]?.id;
    const prazo = await pool.query<{ prazo_devolucao: Date }>(
      "SELECT prazo_devolucao FROM core.movimentacao WHERE id = $1",
      [movimentacaoId],
    );
    res
      .status(201)
      .json({ movimentacao_id: movimentacaoId, prazo: prazo.rows[0]?.prazo_devolucao });
  });

  /**
   * Devolução. O pedido informa também de quem se está recebendo (pessoa_id): se, entre a
   * tela carregar e o toque em "devolver", a unidade tiver sido devolvida e retirada por
   * outra pessoa, o banco recusa (ALM04) em vez de fechar a cautela errada.
   */
  rotas.post("/devolucoes", async (req, res) => {
    const corpo = v.objeto(req.body);
    const unidadeId = v.id(corpo.unidade_id, "unidade_id");
    const pessoaId = v.id(corpo.pessoa_id, "pessoa_id");
    const estado = v.umDe(corpo.estado, "estado", ESTADOS_DE_DEVOLUCAO);
    const observacao = v.textoOpcional(corpo.observacao, "observacao", 500);

    const { rows } = await pool.query<{ id: number }>(
      `SELECT core.registrar_devolucao_unidade(
           p_unidade_id => $1, p_pessoa_id => $2, p_executado_por => $3,
           p_estado => $4, p_observacao => $5) AS id`,
      [unidadeId, pessoaId, usuario(res).id, estado, observacao],
    );
    res.status(201).json({ movimentacao_id: rows[0]?.id });
  });

  return rotas;
}
