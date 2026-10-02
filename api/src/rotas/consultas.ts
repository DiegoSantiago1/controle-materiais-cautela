/**
 * Consultas (qualquer perfil logado): referências para os formulários, resumo do início,
 * militares, estoque, posse, histórico e o ciclo retirada -> posse -> devolução.
 *
 * Todo SQL é escrito à mão e parametrizado ($1, $2...): o valor do usuário nunca é colado
 * no texto da consulta. Os filtros de período usam faixa (>= início AND < fim) sobre a
 * coluna, e não função na coluna, para o índice de ocorrida_em ser usado.
 */
import { type Request, Router } from "express";
import type pg from "pg";
import { ErroHttp } from "../erros.ts";
import * as v from "../validacao.ts";
import { type Dependencias, idDaRota, SEM_ACENTO, usuario, uuid } from "./comum.ts";

const TIPOS = ["ENTRADA", "RETIRADA", "DEVOLUCAO", "MUDANCA_STATUS", "AJUSTE", "ESTORNO"] as const;
const POR_PAGINA = 50;

/** Material em posse, agrupado por atendimento: "3 escudos com o SD Silva desde 08:35". */
export async function posseAgrupada(
  pool: pg.Pool,
  filtros: { pessoa?: number | null; soVencidas?: boolean; limite?: number },
): Promise<unknown[]> {
  const { rows } = await pool.query(
    `SELECT v.pessoa_id, v.posto_graduacao AS posto, v.nome_guerra, v.nome, v.matricula,
            v.setor, v.material_tipo_id, v.codigo, v.material, v.categoria, v.operacao,
            min(v.retirada_em) AS retirada_em, min(v.prazo) AS prazo, min(v.retirada_id) AS retirada_id,
            min(v.prazo) < now() AS vencida,
            v.entregue_por_posto, v.entregue_por_guerra,
            max(v.estado_retirada) AS estado_retirada, max(v.observacao) AS observacao,
            max(v.finalidade) AS finalidade, count(*)::integer AS quantidade,
            json_agg(json_build_object('id', v.unidade_id, 'bmp', v.bmp,
                                       'numero_serie', v.numero_serie)
                     ORDER BY v.bmp) AS unidades
     FROM core.vw_posse v
     WHERE ($1::integer IS NULL OR v.pessoa_id = $1)
     GROUP BY v.pessoa_id, v.posto_graduacao, v.nome_guerra, v.nome, v.matricula, v.setor,
              v.material_tipo_id, v.codigo, v.material, v.categoria, v.operacao,
              coalesce(v.operacao::text, v.retirada_id::text),
              v.entregue_por_posto, v.entregue_por_guerra
     HAVING NOT $2::boolean OR min(v.prazo) < now()
     ORDER BY min(v.prazo), v.nome_guerra, v.material
     LIMIT $3`,
    [filtros.pessoa ?? null, filtros.soVencidas ?? false, filtros.limite ?? 2000],
  );
  return rows;
}

interface FiltroHistorico {
  de?: string | null;
  ate?: string | null;
  tipo?: string | null;
  busca?: string | null;
  material?: number | null;
  pessoa?: number | null;
  antes?: { em: string; id: number } | null;
  limite?: number;
}

/**
 * Histórico agrupado por atendimento: as 3 unidades de uma retirada viram uma linha com
 * quantidade 3. O que não tem código de operação (a história gerada antes da 0014) vira
 * uma linha por movimentação. Paginação por cursor (data e id da última linha vista), que
 * não pula nem repete linha quando entra movimentação nova no meio.
 */
export async function historicoAgrupado(pool: pg.Pool, f: FiltroHistorico): Promise<unknown[]> {
  const termo = f.busca ? `%${v.escaparLike(f.busca)}%` : null;
  const { rows } = await pool.query(
    `SELECT m.operacao, m.tipo, min(m.ocorrida_em) AS ocorrida_em, max(m.id) AS ultimo_id,
            min(m.id) AS primeiro_id,
            t.id AS material_tipo_id, t.codigo, t.nome AS material, t.controle,
            CASE WHEN t.controle = 'CONSUMO' THEN sum(abs(m.variacao)) ELSE count(*) END::integer
                AS quantidade,
            CASE WHEN count(*) = 1 THEN max(u.bmp) END AS bmp,
            p.id AS pessoa_id, p.posto_graduacao AS posto, p.nome_guerra,
            pe.posto_graduacao AS executor_posto, pe.nome_guerra AS executor_guerra,
            max(m.estado_retirada) AS estado_retirada, max(m.estado_devolucao) AS estado_devolucao,
            max(m.status_anterior) AS status_anterior, max(m.status_novo) AS status_novo,
            max(m.observacao) AS observacao, max(m.finalidade) AS finalidade,
            max(m.documento_ref) AS documento, max(m.prazo_devolucao) AS prazo
     FROM core.movimentacao m
     JOIN core.material_tipo t ON t.id = m.material_tipo_id
     LEFT JOIN core.unidade_patrimonial u ON u.id = m.unidade_id
     LEFT JOIN core.pessoa p ON p.id = m.pessoa_id
     JOIN core.usuario ue ON ue.id = m.executado_por
     JOIN core.pessoa pe ON pe.id = ue.pessoa_id
     WHERE ($1::date IS NULL OR m.ocorrida_em >= $1::date)
       AND ($2::date IS NULL OR m.ocorrida_em < $2::date + 1)
       AND ($3::text IS NULL OR m.tipo = $3)
       AND ($5::integer IS NULL OR m.material_tipo_id = $5)
       AND ($6::integer IS NULL OR m.pessoa_id = $6)
       AND ($4::text IS NULL
            OR ${SEM_ACENTO("t.nome")} LIKE ${SEM_ACENTO("$4")} ESCAPE '\\'
            OR t.codigo ILIKE $4 ESCAPE '\\'
            OR u.bmp LIKE $4 ESCAPE '\\'
            OR ${SEM_ACENTO("coalesce(p.posto_graduacao || ' ' || p.nome_guerra, '')")}
               LIKE ${SEM_ACENTO("$4")} ESCAPE '\\'
            OR ${SEM_ACENTO("coalesce(p.nome, '')")} LIKE ${SEM_ACENTO("$4")} ESCAPE '\\'
            OR ${SEM_ACENTO("pe.posto_graduacao || ' ' || pe.nome_guerra")}
               LIKE ${SEM_ACENTO("$4")} ESCAPE '\\')
     GROUP BY coalesce(m.operacao::text, m.id::text), m.operacao, m.tipo, t.id, p.id, pe.id
     HAVING $7::timestamptz IS NULL OR (min(m.ocorrida_em), max(m.id)) < ($7, $8::bigint)
     ORDER BY min(m.ocorrida_em) DESC, max(m.id) DESC
     LIMIT $9`,
    [
      f.de ?? null,
      f.ate ?? null,
      f.tipo ?? null,
      termo,
      f.material ?? null,
      f.pessoa ?? null,
      f.antes?.em ?? null,
      f.antes?.id ?? null,
      f.limite ?? POR_PAGINA,
    ],
  );
  return rows;
}

function textoDaQuery(req: Request, nome: string, maximo: number): string | null {
  const valor = req.query[nome];
  if (valor === undefined || valor === "") return null;
  if (typeof valor !== "string") throw new v.ErroDeValidacao(nome, `${nome} inválido.`);
  return v.textoOpcional(valor, nome, maximo);
}

function idDaQuery(req: Request, nome: string): number | null {
  const valor = textoDaQuery(req, nome, 12);
  if (valor === null) return null;
  if (!/^[1-9][0-9]{0,9}$/.test(valor)) throw new v.ErroDeValidacao(nome, `${nome} inválido.`);
  return v.id(Number(valor), nome);
}

export function rotasDeConsulta(dep: Dependencias): Router {
  const { pool } = dep;
  const rotas = Router();

  /** Listas que os formulários e filtros usam. */
  rotas.get("/referencias", async (_req, res) => {
    const [postos, setores, locais, categorias] = await Promise.all([
      pool.query("SELECT sigla, nome, circulo FROM core.posto_graduacao ORDER BY ordem"),
      pool.query("SELECT id, sigla, nome FROM core.setor ORDER BY sigla"),
      pool.query("SELECT id, nome FROM core.local_armazenagem ORDER BY nome"),
      pool.query(
        `SELECT c.id, c.nome,
                coalesce(json_agg(json_build_object('id', s.id, 'nome', s.nome) ORDER BY s.nome)
                         FILTER (WHERE s.id IS NOT NULL), '[]') AS subcategorias
         FROM core.categoria c
         LEFT JOIN core.subcategoria s ON s.categoria_id = c.id
         GROUP BY c.id
         ORDER BY c.nome`,
      ),
    ]);
    res.json({
      postos: postos.rows,
      setores: setores.rows,
      locais: locais.rows,
      categorias: categorias.rows,
    });
  });

  /** Painel do início: contadores operacionais (sem gráfico) e as listas de atenção. */
  rotas.get("/resumo", async (_req, res) => {
    const [contadores, vencidas, ultimas] = await Promise.all([
      pool.query(
        `SELECT
           (SELECT count(*) FROM core.unidade_patrimonial WHERE status = 'CAUTELADA')::integer
               AS em_posse,
           (SELECT count(DISTINCT detentor_id) FROM core.unidade_patrimonial
            WHERE status = 'CAUTELADA')::integer AS militares_com_material,
           (SELECT count(DISTINCT (pessoa_id, material_tipo_id,
                                  coalesce(operacao::text, retirada_id::text)))
            FROM core.vw_posse WHERE prazo < now())::integer AS vencidas,
           (SELECT count(*) FROM core.vw_estoque
            WHERE ativo AND situacao <> 'NORMAL')::integer AS abaixo_do_minimo,
           (SELECT count(*) FROM core.unidade_patrimonial
            WHERE status = 'EM_MANUTENCAO')::integer AS em_manutencao,
           (SELECT count(DISTINCT coalesce(operacao::text, id::text)) FROM core.movimentacao
            WHERE tipo = 'RETIRADA' AND ocorrida_em >= date_trunc('day', now()))::integer
               AS retiradas_hoje,
           (SELECT count(DISTINCT coalesce(operacao::text, id::text)) FROM core.movimentacao
            WHERE tipo = 'DEVOLUCAO' AND ocorrida_em >= date_trunc('day', now()))::integer
               AS devolucoes_hoje`,
      ),
      posseAgrupada(pool, { soVencidas: true, limite: 6 }),
      historicoAgrupado(pool, { limite: 8 }),
    ]);
    res.json({ contadores: contadores.rows[0], vencidas, ultimas });
  });

  /** Militares na unidade, para escolher quem retira ou devolve. */
  rotas.get("/pessoas", async (req, res) => {
    const termo = v.termoDeBusca(req.query.busca);
    const { rows } = await pool.query(
      `SELECT p.id, p.posto_graduacao AS posto, p.nome_guerra, p.nome, p.matricula,
              s.sigla AS setor,
              (SELECT count(*) FROM core.unidade_patrimonial u
               WHERE u.detentor_id = p.id AND u.status = 'CAUTELADA')::integer AS em_posse
       FROM core.pessoa p
       JOIN core.setor s ON s.id = p.setor_id
       JOIN core.posto_graduacao pg ON pg.sigla = p.posto_graduacao
       WHERE p.data_entrada <= core.data_local(now())
         AND (p.data_saida IS NULL OR p.data_saida > core.data_local(now()))
         AND (p.matricula LIKE $1 ESCAPE '\\'
              OR ${SEM_ACENTO("p.posto_graduacao || ' ' || p.nome_guerra")}
                 LIKE ${SEM_ACENTO("$2")} ESCAPE '\\'
              OR ${SEM_ACENTO("p.nome")} LIKE ${SEM_ACENTO("$2")} ESCAPE '\\')
       ORDER BY lower(p.nome_guerra)
       LIMIT 20`,
      [`${v.escaparLike(termo)}%`, `%${v.escaparLike(termo)}%`],
    );
    res.json({ pessoas: rows });
  });

  /**
   * Todos os militares (inclusive os que já saíram). Login e perfil de quem tem usuário só
   * vão para o administrador: a lista de logins ajudaria a adivinhar senhas, e o login
   * cuida de não revelar quais existem (D21).
   */
  rotas.get("/militares", async (_req, res) => {
    const admin = usuario(res).perfil === "ADMINISTRADOR";
    const { rows } = await pool.query(
      `SELECT p.id, p.posto_graduacao AS posto, pg.ordem AS posto_ordem, p.nome_guerra, p.nome,
              p.matricula, p.setor_id, s.sigla AS setor, p.data_entrada, p.data_saida,
              p.data_saida IS NULL OR p.data_saida > core.data_local(now()) AS na_unidade,
              CASE WHEN $1 THEN u.id END AS usuario_id,
              CASE WHEN $1 THEN u.login END AS login,
              CASE WHEN $1 THEN u.perfil END AS perfil,
              CASE WHEN $1 THEN u.ativo END AS usuario_ativo,
              (SELECT count(*) FROM core.unidade_patrimonial x
               WHERE x.detentor_id = p.id AND x.status = 'CAUTELADA')::integer AS em_posse
       FROM core.pessoa p
       JOIN core.setor s ON s.id = p.setor_id
       JOIN core.posto_graduacao pg ON pg.sigla = p.posto_graduacao
       LEFT JOIN core.usuario u ON u.pessoa_id = p.id
       ORDER BY p.data_saida IS NOT NULL, pg.ordem DESC, lower(p.nome_guerra)`,
      [admin],
    );
    res.json({ militares: rows });
  });

  /** Estoque de todos os materiais (os filtros são feitos na tela: são poucas centenas). */
  rotas.get("/estoque", async (_req, res) => {
    const { rows } = await pool.query(
      `SELECT material_tipo_id AS id, codigo, nome, descricao, controle, unidade_medida,
              prazo_devolucao_horas, custo_unitario::float8 AS custo_unitario, ativo,
              categoria_id, categoria, subcategoria_id, subcategoria, total, disponivel,
              em_posse, em_manutencao, indisponivel, estoque_minimo, situacao
       FROM core.vw_estoque
       ORDER BY categoria, nome`,
    );
    res.json({ materiais: rows });
  });

  /** Um material: os números, as unidades (com quem está cada uma) e o último movimento. */
  rotas.get("/estoque/:id", async (req, res) => {
    const id = idDaRota(req);
    const material = await pool.query(
      `SELECT e.material_tipo_id AS id, e.codigo, e.nome, e.descricao, e.controle,
              e.unidade_medida, e.prazo_devolucao_horas, e.custo_unitario::float8 AS custo_unitario,
              e.ativo, e.categoria_id, e.categoria, e.subcategoria_id, e.subcategoria, e.total,
              e.disponivel, e.em_posse, e.em_manutencao, e.indisponivel, e.estoque_minimo,
              e.situacao, sc.estoque_maximo, l.id AS local_id, l.nome AS local
       FROM core.vw_estoque e
       LEFT JOIN core.saldo_consumo sc ON sc.material_tipo_id = e.material_tipo_id
       LEFT JOIN core.local_armazenagem l ON l.id = sc.local_id
       WHERE e.material_tipo_id = $1`,
      [id],
    );
    if (material.rows.length === 0) {
      throw new ErroHttp(404, "Material não encontrado.", "NAO_ENCONTRADO");
    }
    const [unidades, movimentos] = await Promise.all([
      pool.query(
        `SELECT u.id, u.bmp, u.numero_serie, u.status, l.nome AS local,
                p.id AS pessoa_id, p.posto_graduacao AS posto, p.nome_guerra
         FROM core.unidade_patrimonial u
         JOIN core.local_armazenagem l ON l.id = u.local_id
         LEFT JOIN core.pessoa p ON p.id = u.detentor_id
         WHERE u.material_tipo_id = $1
         ORDER BY array_position(ARRAY['DISPONIVEL', 'CAUTELADA', 'EM_MANUTENCAO',
                                       'NAO_LOCALIZADA', 'BAIXA_PENDENTE',
                                       'AGUARDANDO_TOMBAMENTO', 'BAIXADA'], u.status),
                  u.bmp NULLS LAST`,
        [id],
      ),
      historicoAgrupado(pool, { material: id, limite: 10 }),
    ]);
    res.json({ material: material.rows[0], unidades: unidades.rows, movimentos });
  });

  /** Unidades cauteláveis por BMP, número de série ou nome do material. */
  rotas.get("/unidades", async (req, res) => {
    const termo = v.termoDeBusca(req.query.busca);
    const { rows } = await pool.query(
      `SELECT u.id, u.bmp, u.numero_serie, u.status, t.id AS material_tipo_id, t.codigo,
              t.nome AS material, t.prazo_devolucao_horas,
              p.posto_graduacao AS detentor_posto, p.nome_guerra AS detentor_guerra
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

  /** Material em posse, agrupado por atendimento (de todos, ou de um militar). */
  rotas.get("/posse", async (req, res) => {
    res.json({ grupos: await posseAgrupada(pool, { pessoa: idDaQuery(req, "pessoa_id") }) });
  });

  /** Histórico (página de 50), com filtros de período, tipo, texto, material e militar. */
  rotas.get("/movimentacoes", async (req, res) => {
    const tipo = textoDaQuery(req, "tipo", 20);
    if (tipo !== null && !(TIPOS as readonly string[]).includes(tipo)) {
      throw new v.ErroDeValidacao("tipo", `tipo deve ser um de: ${TIPOS.join(", ")}.`);
    }
    const de = v.dataOpcional(textoDaQuery(req, "de", 10), "de");
    const ate = v.dataOpcional(textoDaQuery(req, "ate", 10), "ate");
    if (de !== null && ate !== null && de > ate) {
      throw new v.ErroDeValidacao("ate", "A data final é anterior à inicial.");
    }
    const antesEm = textoDaQuery(req, "antes_em", 40);
    const antesId = idDaQuery(req, "antes_id");
    if (
      (antesEm === null) !== (antesId === null) ||
      (antesEm && Number.isNaN(Date.parse(antesEm)))
    ) {
      throw new v.ErroDeValidacao("antes_em", "Cursor de página inválido.");
    }
    const linhas = await historicoAgrupado(pool, {
      de,
      ate,
      tipo,
      busca: textoDaQuery(req, "busca", 60),
      material: idDaQuery(req, "material_id"),
      pessoa: idDaQuery(req, "pessoa_id"),
      antes: antesEm !== null && antesId !== null ? { em: antesEm, id: antesId } : null,
      limite: POR_PAGINA + 1, // um a mais: diz se existe a página seguinte
    });
    res.json({ movimentacoes: linhas.slice(0, POR_PAGINA), tem_mais: linhas.length > POR_PAGINA });
  });

  /**
   * O ciclo de um atendimento: para cada unidade, a retirada que abriu a posse e o que a
   * fechou (devolução, mudança de situação ou estorno), ou "ainda em posse".
   * ?operacao=<uuid> (atendimentos novos) ou ?movimentacao=<id> (qualquer linha).
   */
  rotas.get("/ciclo", async (req, res) => {
    const operacao = req.query.operacao === undefined ? null : uuid(req.query.operacao);
    const movimentacao = operacao === null ? idDaQuery(req, "movimentacao") : null;
    if (operacao === null && movimentacao === null) {
      throw new v.ErroDeValidacao("operacao", "Informe a operação ou a movimentação.");
    }
    const { rows } = await pool.query(
      `WITH alvo AS (
           SELECT * FROM core.movimentacao
           WHERE ($1::uuid IS NOT NULL AND operacao = $1) OR id = $2
       ),
       aberturas AS (
           SELECT DISTINCT ON (a.id) a.id AS alvo_id, r.*
           FROM alvo a
           JOIN core.movimentacao r ON r.unidade_id = a.unidade_id AND r.tipo = 'RETIRADA'
                                    AND (r.ocorrida_em, r.id) <= (a.ocorrida_em, a.id)
           ORDER BY a.id, r.ocorrida_em DESC, r.id DESC
       )
       SELECT a.id, a.tipo, a.unidade_id, u.bmp, t.nome AS material, t.codigo, t.controle,
              abs(a.variacao) AS quantidade, a.ocorrida_em,
              json_build_object(
                  'id', ab.id, 'em', ab.ocorrida_em, 'prazo', ab.prazo_devolucao,
                  'estado', ab.estado_retirada, 'observacao', ab.observacao,
                  'finalidade', ab.finalidade,
                  'militar', pr.posto_graduacao || ' ' || pr.nome_guerra,
                  'entregue_por', er.posto_graduacao || ' ' || er.nome_guerra) AS retirada,
              CASE WHEN fe.id IS NOT NULL THEN json_build_object(
                  'id', fe.id, 'tipo', fe.tipo, 'em', fe.ocorrida_em,
                  'estado', fe.estado_devolucao, 'status_novo', fe.status_novo,
                  'observacao', fe.observacao,
                  'militar', pf.posto_graduacao || ' ' || pf.nome_guerra,
                  'recebido_por', ef.posto_graduacao || ' ' || ef.nome_guerra) END AS fechamento
       FROM alvo a
       JOIN core.material_tipo t ON t.id = a.material_tipo_id
       LEFT JOIN core.unidade_patrimonial u ON u.id = a.unidade_id
       LEFT JOIN aberturas ab ON ab.alvo_id = a.id
       LEFT JOIN core.pessoa pr ON pr.id = ab.pessoa_id
       LEFT JOIN core.usuario ur ON ur.id = ab.executado_por
       LEFT JOIN core.pessoa er ON er.id = ur.pessoa_id
       LEFT JOIN LATERAL (
           SELECT f.* FROM core.movimentacao f
           WHERE ab.id IS NOT NULL AND f.unidade_id = ab.unidade_id
             AND (f.ocorrida_em, f.id) > (ab.ocorrida_em, ab.id)
             AND f.tipo IN ('DEVOLUCAO', 'MUDANCA_STATUS', 'ESTORNO')
           ORDER BY f.ocorrida_em, f.id
           LIMIT 1
       ) fe ON true
       LEFT JOIN core.pessoa pf ON pf.id = fe.pessoa_id
       LEFT JOIN core.usuario uf ON uf.id = fe.executado_por
       LEFT JOIN core.pessoa ef ON ef.id = uf.pessoa_id
       ORDER BY u.bmp NULLS LAST, a.id`,
      [operacao, movimentacao],
    );
    if (rows.length === 0) throw new ErroHttp(404, "Operação não encontrada.", "NAO_ENCONTRADO");
    res.json({ itens: rows });
  });

  return rotas;
}
