/**
 * Operação de balcão (retirada e devolução) e gestão de estoque (entradas, ajuste de
 * inventário, mudança de situação de uma unidade).
 *
 * Quem entrega e quem recebe não vem do pedido: é o dono da sessão, que o banco descobre
 * pelo hash do token (funções app.*, migração 0015).
 */
import { randomUUID } from "node:crypto";
import { Router } from "express";
import { ErroHttp } from "../erros.ts";
import * as v from "../validacao.ts";
import {
  type Dependencias,
  emTransacao,
  exigirPerfil,
  GESTAO_DE_ESTOQUE,
  idDaRota,
  OPERACIONAIS,
  sessao,
} from "./comum.ts";

const ESTADOS_DE_RETIRADA = ["BOM", "REGULAR"] as const;
const ESTADOS_DE_DEVOLUCAO = ["BOM", "AVARIADO", "INSERVIVEL"] as const;
const SITUACOES = [
  "DISPONIVEL",
  "EM_MANUTENCAO",
  "NAO_LOCALIZADA",
  "BAIXA_PENDENTE",
  "BAIXADA",
] as const;
const MAX_ITENS = 20;

interface Item {
  material: number;
  quantidade: number | null;
  unidades: number[] | null;
}

function itensDaRetirada(valor: unknown): Item[] {
  if (!Array.isArray(valor) || valor.length === 0 || valor.length > MAX_ITENS) {
    throw new v.ErroDeValidacao("itens", `Informe de 1 a ${MAX_ITENS} materiais.`);
  }
  const itens = valor.map((bruto, i) => {
    const item = v.objeto(bruto);
    const campo = `itens[${i}]`;
    const material = v.id(item.material_id, `${campo}.material_id`);
    const unidades =
      item.unidades === undefined || item.unidades === null
        ? null
        : v.listaDeIds(item.unidades, `${campo}.unidades`, 500);
    const quantidade =
      unidades === null ? v.inteiro(item.quantidade, `${campo}.quantidade`, 1, 500) : null;
    return { material, quantidade, unidades };
  });
  if (new Set(itens.map((i) => i.material)).size !== itens.length) {
    throw new v.ErroDeValidacao(
      "itens",
      "O mesmo material aparece duas vezes: junte as quantidades.",
    );
  }
  return itens;
}

export function rotasDeOperacao(dep: Dependencias): Router {
  const { pool } = dep;
  const rotas = Router();

  /**
   * Retirada: um militar leva um ou mais materiais. Tudo numa transação e com o mesmo
   * código de operação: se faltar um item, nada sai.
   */
  rotas.post("/retiradas", exigirPerfil(OPERACIONAIS), async (req, res) => {
    const corpo = v.objeto(req.body);
    const pessoa = v.id(corpo.pessoa_id, "pessoa_id");
    const itens = itensDaRetirada(corpo.itens);
    const estado = v.umDe(corpo.estado ?? "BOM", "estado", ESTADOS_DE_RETIRADA);
    const finalidade = v.textoOpcional(corpo.finalidade, "finalidade", 120);
    const observacao = v.textoOpcional(corpo.observacao, "observacao", 500);
    const operacao = randomUUID();

    const saiu = await emTransacao(pool, async (cliente) => {
      for (const item of itens) {
        await cliente.query("SELECT app.retirar($1, $2, $3, $4, $5, $6, $7, $8, $9)", [
          sessao(res),
          item.material,
          item.quantidade,
          pessoa,
          operacao,
          estado,
          finalidade,
          observacao,
          item.unidades,
        ]);
      }
      const { rows } = await cliente.query(
        `SELECT t.id AS material_tipo_id, t.nome AS material, t.controle,
                CASE WHEN t.controle = 'CONSUMO' THEN sum(abs(m.variacao))
                     ELSE count(*) END::integer AS quantidade,
                min(m.prazo_devolucao) AS prazo, min(m.ocorrida_em) AS ocorrida_em,
                coalesce(json_agg(u.bmp ORDER BY u.bmp) FILTER (WHERE u.bmp IS NOT NULL), '[]')
                    AS bmps
         FROM core.movimentacao m
         JOIN core.material_tipo t ON t.id = m.material_tipo_id
         LEFT JOIN core.unidade_patrimonial u ON u.id = m.unidade_id
         WHERE m.operacao = $1
         GROUP BY t.id
         ORDER BY t.nome`,
        [operacao],
      );
      return rows;
    });
    res.status(201).json({ operacao, itens: saiu });
  });

  /**
   * Devolução: unidades que estão com o militar, todas no mesmo estado. Se uma delas não
   * estiver com ele (foi devolvida por outro balcão enquanto a tela estava aberta), o
   * banco recusa tudo (ALM04/ALM02) em vez de fechar a posse errada.
   */
  rotas.post("/devolucoes", exigirPerfil(OPERACIONAIS), async (req, res) => {
    const corpo = v.objeto(req.body);
    const pessoa = v.id(corpo.pessoa_id, "pessoa_id");
    const unidades = v.listaDeIds(corpo.unidades, "unidades", 500);
    const estado = v.umDe(corpo.estado ?? "BOM", "estado", ESTADOS_DE_DEVOLUCAO);
    const observacao = v.textoOpcional(corpo.observacao, "observacao", 500);
    const { rows } = await pool.query<{ operacao: string }>(
      "SELECT app.devolver($1, $2, $3, $4, $5, NULL) AS operacao",
      [sessao(res), unidades, pessoa, estado, observacao],
    );
    res.status(201).json({ operacao: rows[0]?.operacao, quantidade: unidades.length });
  });

  /**
   * Entrada de material. Patrimonial: N unidades novas, com BMP sequencial. Consumo: soma
   * ao saldo.
   */
  rotas.post("/materiais/:id/entradas", exigirPerfil(GESTAO_DE_ESTOQUE), async (req, res) => {
    const material = idDaRota(req);
    const corpo = v.objeto(req.body);
    const quantidade = v.inteiro(corpo.quantidade, "quantidade", 1, 100_000);
    const documento = v.textoOpcional(corpo.documento, "documento", 40);
    const observacao = v.textoOpcional(corpo.observacao, "observacao", 500);
    const { rows } = await pool.query<{ controle: string }>(
      "SELECT controle FROM core.material_tipo WHERE id = $1",
      [material],
    );
    const controle = rows[0]?.controle;
    if (controle === undefined)
      throw new ErroHttp(404, "Material não encontrado.", "NAO_ENCONTRADO");

    if (controle === "SERIAL") {
      if (quantidade > 500) {
        throw new v.ErroDeValidacao("quantidade", "No máximo 500 unidades por entrada.");
      }
      const local = v.id(corpo.local_id, "local_id");
      const estado = v.umDe(corpo.estado ?? "BOM", "estado", ESTADOS_DE_DEVOLUCAO);
      const r = await pool.query<{ ids: number[] }>(
        "SELECT app.entrada_lote($1, $2, $3, $4, $5, $6, $7) AS ids",
        [sessao(res), material, quantidade, local, estado, observacao, documento],
      );
      const ids = r.rows[0]?.ids ?? [];
      const bmps = await pool.query<{ bmp: string }>(
        "SELECT bmp FROM core.unidade_patrimonial WHERE id = ANY($1) ORDER BY bmp",
        [ids],
      );
      res.status(201).json({ quantidade: ids.length, bmps: bmps.rows.map((b) => b.bmp) });
      return;
    }
    await pool.query("SELECT app.entrada_consumo($1, $2, $3, $4, $5)", [
      sessao(res),
      material,
      quantidade,
      documento,
      observacao,
    ]);
    res.status(201).json({ quantidade });
  });

  /** Ajuste de inventário (consumo): informa o que foi CONTADO; o banco calcula a diferença. */
  rotas.post("/materiais/:id/ajuste", exigirPerfil(GESTAO_DE_ESTOQUE), async (req, res) => {
    const material = idDaRota(req);
    const corpo = v.objeto(req.body);
    const contada = v.inteiro(corpo.quantidade_contada, "quantidade_contada", 0, 10_000_000);
    const justificativa = v.texto(corpo.justificativa, "justificativa", 500);
    if (justificativa === "") {
      throw new v.ErroDeValidacao("justificativa", "Explique o motivo do ajuste.");
    }
    const { rows } = await pool.query<{ id: number | null }>(
      "SELECT app.ajustar_consumo($1, $2, $3, $4) AS id",
      [sessao(res), material, contada, justificativa],
    );
    res.status(201).json({ ajustado: rows[0]?.id !== null });
  });

  /** Situação de uma unidade fora do ciclo de cautela (manutenção, extravio, baixa). */
  rotas.post("/unidades/:id/situacao", exigirPerfil(GESTAO_DE_ESTOQUE), async (req, res) => {
    const unidade = idDaRota(req);
    const corpo = v.objeto(req.body);
    const status = v.umDe(corpo.status, "status", SITUACOES);
    const justificativa = v.texto(corpo.justificativa, "justificativa", 500);
    if (justificativa === "") {
      throw new v.ErroDeValidacao("justificativa", "Explique o motivo da mudança.");
    }
    const bmp = v.textoOpcional(corpo.bmp, "bmp", 7);
    await pool.query("SELECT app.alterar_status_unidade($1, $2, $3, $4, $5)", [
      sessao(res),
      unidade,
      status,
      justificativa,
      bmp,
    ]);
    res.status(201).json({ status });
  });

  return rotas;
}
