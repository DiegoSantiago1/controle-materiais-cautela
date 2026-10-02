/**
 * Administração (só ADMINISTRADOR): categorias, materiais, militares, usuários, senhas e a
 * auditoria. Cada rota valida o formato e chama a função app.* correspondente; as regras
 * (duplicado, último administrador, saída com material em posse...) moram no banco.
 */
import { Router } from "express";
import { gerarHash } from "../senha.ts";
import * as v from "../validacao.ts";
import {
  ADMINISTRACAO,
  type Dependencias,
  emTransacao,
  exigirPerfil,
  idDaRota,
  sessao,
} from "./comum.ts";
import { senhaNova } from "./sessao.ts";

const CONTROLES = ["SERIAL", "CONSUMO"] as const;
const UNIDADES_DE_MEDIDA = [
  "UN",
  "CX",
  "PCT",
  "RESMA",
  "L",
  "GL",
  "KG",
  "M",
  "ROLO",
  "PAR",
  "FRASCO",
] as const;
const PERFIS = ["ADMINISTRADOR", "ESTOQUISTA", "EQUIPAMENTISTA", "CONSULTA"] as const;
const SO_ADMIN = exigirPerfil(ADMINISTRACAO);

function nome(valor: unknown, campo: string, maximo = 120): string {
  const texto = v.texto(valor, campo, maximo);
  if (texto === "") throw new v.ErroDeValidacao(campo, `Informe ${campo}.`);
  return texto;
}

export function rotasDeAdministracao(dep: Dependencias): Router {
  const { pool } = dep;
  const rotas = Router();

  // ------------------------------------------------------------ categorias
  rotas.post("/categorias", SO_ADMIN, async (req, res) => {
    const corpo = v.objeto(req.body);
    const { rows } = await pool.query<{ id: number }>(
      "SELECT app.cadastrar_categoria($1, $2) AS id",
      [sessao(res), nome(corpo.nome, "nome")],
    );
    res.status(201).json({ id: rows[0]?.id });
  });

  rotas.patch("/categorias/:id", SO_ADMIN, async (req, res) => {
    const corpo = v.objeto(req.body);
    await pool.query("SELECT app.renomear_categoria($1, $2, $3)", [
      sessao(res),
      idDaRota(req),
      nome(corpo.nome, "nome"),
    ]);
    res.status(204).end();
  });

  rotas.post("/subcategorias", SO_ADMIN, async (req, res) => {
    const corpo = v.objeto(req.body);
    const { rows } = await pool.query<{ id: number }>(
      "SELECT app.cadastrar_subcategoria($1, $2, $3) AS id",
      [sessao(res), v.id(corpo.categoria_id, "categoria_id"), nome(corpo.nome, "nome")],
    );
    res.status(201).json({ id: rows[0]?.id });
  });

  rotas.patch("/subcategorias/:id", SO_ADMIN, async (req, res) => {
    const corpo = v.objeto(req.body);
    await pool.query("SELECT app.renomear_subcategoria($1, $2, $3)", [
      sessao(res),
      idDaRota(req),
      nome(corpo.nome, "nome"),
    ]);
    res.status(204).end();
  });

  // ------------------------------------------------------------ materiais
  rotas.post("/materiais", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    const controle = v.umDe(c.controle, "controle", CONTROLES);
    const { rows } = await pool.query<{ id: number }>(
      "SELECT app.cadastrar_material($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) AS id",
      [
        sessao(res),
        nome(c.nome, "nome"),
        v.id(c.subcategoria_id, "subcategoria_id"),
        controle,
        v.umDe(c.unidade_medida ?? "UN", "unidade_medida", UNIDADES_DE_MEDIDA),
        v.inteiroOpcional(c.prazo_devolucao_horas, "prazo_devolucao_horas", 1, 8760),
        v.inteiroOpcional(c.estoque_minimo, "estoque_minimo", 0, 1_000_000),
        v.inteiroOpcional(c.estoque_maximo, "estoque_maximo", 1, 1_000_000),
        v.idOpcional(c.local_id, "local_id"),
        v.dinheiro(c.custo_unitario ?? 0, "custo_unitario"),
        v.textoOpcional(c.descricao, "descricao", 500),
      ],
    );
    res.status(201).json({ id: rows[0]?.id });
  });

  rotas.put("/materiais/:id", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    await pool.query("SELECT app.atualizar_material($1, $2, $3, $4, $5, $6, $7, $8, $9)", [
      sessao(res),
      idDaRota(req),
      nome(c.nome, "nome"),
      v.id(c.subcategoria_id, "subcategoria_id"),
      v.inteiroOpcional(c.prazo_devolucao_horas, "prazo_devolucao_horas", 1, 8760),
      v.inteiroOpcional(c.estoque_minimo, "estoque_minimo", 0, 1_000_000),
      v.dinheiro(c.custo_unitario, "custo_unitario"),
      v.textoOpcional(c.descricao, "descricao", 500),
      v.booleano(c.ativo, "ativo"),
    ]);
    res.status(204).end();
  });

  // ------------------------------------------------------------ militares
  rotas.post("/militares", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    const { rows } = await pool.query<{ id: number }>(
      "SELECT app.cadastrar_pessoa($1, $2, $3, $4, $5, $6, $7) AS id",
      [
        sessao(res),
        v.texto(c.matricula, "matricula", 7),
        nome(c.nome, "nome"),
        nome(c.nome_guerra, "nome_guerra", 30),
        v.texto(c.posto, "posto", 10),
        v.id(c.setor_id, "setor_id"),
        v.dataOpcional(c.data_entrada, "data_entrada"),
      ],
    );
    res.status(201).json({ id: rows[0]?.id });
  });

  rotas.put("/militares/:id", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    await pool.query("SELECT app.atualizar_pessoa($1, $2, $3, $4, $5, $6)", [
      sessao(res),
      idDaRota(req),
      nome(c.nome, "nome"),
      nome(c.nome_guerra, "nome_guerra", 30),
      v.texto(c.posto, "posto", 10),
      v.id(c.setor_id, "setor_id"),
    ]);
    res.status(204).end();
  });

  rotas.post("/militares/:id/saida", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    await pool.query("SELECT app.registrar_saida_pessoa($1, $2, $3)", [
      sessao(res),
      idDaRota(req),
      v.data(c.data_saida, "data_saida"),
    ]);
    res.status(204).end();
  });

  // ------------------------------------------------------------ usuários
  rotas.get("/usuarios", SO_ADMIN, async (_req, res) => {
    const { rows } = await pool.query(
      `SELECT u.id, u.login, u.perfil, u.ativo, p.id AS pessoa_id,
              p.posto_graduacao AS posto, p.nome_guerra, p.nome,
              c.usuario_id IS NOT NULL AS tem_senha, c.atualizada_em AS senha_atualizada_em,
              (SELECT max(s.criada_em) FROM app.sessao s WHERE s.usuario_id = u.id)
                  AS ultima_entrada
       FROM core.usuario u
       JOIN core.pessoa p ON p.id = u.pessoa_id
       LEFT JOIN app.credencial c ON c.usuario_id = u.id
       ORDER BY u.ativo DESC, array_position(ARRAY['ADMINISTRADOR', 'ESTOQUISTA',
                'EQUIPAMENTISTA', 'CONSULTA'], u.perfil), u.login`,
    );
    res.json({ usuarios: rows });
  });

  /** Novo usuário já com a senha inicial: os dois passos na mesma transação. */
  rotas.post("/usuarios", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    const pessoa = v.id(c.pessoa_id, "pessoa_id");
    const login = v.texto(c.login, "login", 32);
    const perfil = v.umDe(c.perfil, "perfil", PERFIS);
    const hash = await gerarHash(senhaNova(c.senha));
    const id = await emTransacao(pool, async (cliente) => {
      const { rows } = await cliente.query<{ id: number }>(
        "SELECT app.cadastrar_usuario($1, $2, $3, $4) AS id",
        [sessao(res), pessoa, login, perfil],
      );
      const novo = rows[0]?.id;
      await cliente.query("SELECT app.definir_senha($1, $2, $3)", [sessao(res), novo, hash]);
      return novo;
    });
    res.status(201).json({ id });
  });

  rotas.patch("/usuarios/:id", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    await pool.query("SELECT app.alterar_usuario($1, $2, $3, $4)", [
      sessao(res),
      idDaRota(req),
      v.umDe(c.perfil, "perfil", PERFIS),
      v.booleano(c.ativo, "ativo"),
    ]);
    res.status(204).end();
  });

  rotas.post("/usuarios/:id/senha", SO_ADMIN, async (req, res) => {
    const c = v.objeto(req.body);
    const hash = await gerarHash(senhaNova(c.senha));
    await pool.query("SELECT app.definir_senha($1, $2, $3)", [sessao(res), idDaRota(req), hash]);
    res.status(204).end();
  });

  // ------------------------------------------------------------ auditoria
  rotas.get("/auditoria", SO_ADMIN, async (_req, res) => {
    const { rows } = await pool.query(
      `SELECT a.id, a.ocorrida_em, a.acao, a.entidade, a.entidade_id, a.detalhe,
              p.posto_graduacao AS executor_posto, p.nome_guerra AS executor_guerra,
              CASE a.entidade
                  WHEN 'MATERIAL' THEN (SELECT nome FROM core.material_tipo WHERE id = a.entidade_id)
                  WHEN 'CATEGORIA' THEN (SELECT nome FROM core.categoria WHERE id = a.entidade_id)
                  WHEN 'SUBCATEGORIA' THEN
                      (SELECT nome FROM core.subcategoria WHERE id = a.entidade_id)
                  WHEN 'PESSOA' THEN (SELECT posto_graduacao || ' ' || nome_guerra
                                      FROM core.pessoa WHERE id = a.entidade_id)
                  WHEN 'USUARIO' THEN (SELECT login FROM core.usuario WHERE id = a.entidade_id)
              END AS alvo
       FROM core.auditoria a
       JOIN core.usuario u ON u.id = a.executado_por
       JOIN core.pessoa p ON p.id = u.pessoa_id
       ORDER BY a.ocorrida_em DESC, a.id DESC
       LIMIT 200`,
    );
    res.json({ registros: rows });
  });

  return rotas;
}
