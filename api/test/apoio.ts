/**
 * Apoio dos testes de integração da API.
 *
 * Cada arquivo de teste monta o próprio cenário no banco de TESTES (setor, pessoas,
 * usuários com senha, um material com unidades), com um sufixo aleatório nos nomes: os
 * testes podem rodar de novo sem limpar nada (o histórico é imutável e não aceita
 * DELETE) e sem colidir com os dados dos testes do Python.
 *
 * A API conecta como o usuário da aplicação (menor privilégio), como em produção. O dono
 * do banco só monta o cenário e confere o que foi gravado.
 */
import { randomInt } from "node:crypto";
import { once } from "node:events";
import type { AddressInfo } from "node:net";
import type pg from "pg";
import { criarApp } from "../src/app.ts";
import { carregarArquivoEnv, carregarConfig } from "../src/config.ts";
import { criarPool } from "../src/db.ts";
import { LimiteDeTentativas } from "../src/limite.ts";
import { gerarHash } from "../src/senha.ts";

export const SENHA = "senha-de-teste-123";
export const MAX_FALHAS_LOGIN = 3;

export interface Cenario {
  sufixo: string;
  material: string; // nome do material, com acento ("Rádio de teste ...")
  materialId: number;
  unidades: { id: number; bmp: string }[];
  consumo: { id: number; saldo: number }; // material de consumo com saldo
  local: number;
  setor: number;
  categoria: number;
  subcategoria: number;
  pessoa: number; // na unidade
  pessoa2: number; // na unidade
  transferida: number; // saiu da unidade
  equipamentista: { id: number; login: string };
  admin: { id: number; login: string };
  consulta: { id: number; login: string };
  inativo: { id: number; login: string };
  estoquista: number;
}

export interface Ambiente {
  url: string;
  dono: pg.Pool;
  api: pg.Pool;
  cenario: Cenario;
  fechar: () => Promise<void>;
}

function letras(n: number, maiusculas = true): string {
  const alfabeto = maiusculas ? "ABCDEFGHIJKLMNOPQRSTUVWXYZ" : "abcdefghijklmnopqrstuvwxyz";
  return Array.from({ length: n }, () => alfabeto[randomInt(26)]).join("");
}

function digitos(n: number): string {
  return Array.from({ length: n }, () => String(randomInt(10))).join("");
}

/** Repete a inserção com outro valor aleatório se bater num UNIQUE (improvável). */
async function unico<T>(tentar: () => Promise<T>): Promise<T> {
  for (let i = 0; ; i++) {
    try {
      return await tentar();
    } catch (erro) {
      if ((erro as { code?: string }).code !== "23505" || i >= 5) throw erro;
    }
  }
}

async function inserir(pool: pg.Pool, sql: string, valores: unknown[]): Promise<number> {
  const { rows } = await pool.query<{ id: number }>(sql, valores);
  const id = rows[0]?.id;
  if (id === undefined) throw new Error(`nada inserido: ${sql}`);
  return id;
}

async function criarCenario(dono: pg.Pool): Promise<Cenario> {
  const sufixo = letras(4);
  const s = sufixo.toLowerCase();
  const setor = await inserir(
    dono,
    "INSERT INTO core.setor (sigla, nome) VALUES ($1, $2) RETURNING id",
    [`TA${sufixo}`, `Setor API ${sufixo}`],
  );
  const local = await inserir(
    dono,
    "INSERT INTO core.local_armazenagem (nome) VALUES ($1) RETURNING id",
    [`Local API ${sufixo}`],
  );
  const categoria = await inserir(
    dono,
    "INSERT INTO core.categoria (nome) VALUES ($1) RETURNING id",
    [`Categoria API ${sufixo}`],
  );
  const subcategoria = await inserir(
    dono,
    "INSERT INTO core.subcategoria (categoria_id, nome) VALUES ($1, $2) RETURNING id",
    [categoria, `Subcategoria API ${sufixo}`],
  );

  const pessoa = (nome: string, saida: string | null = null) =>
    unico(() =>
      inserir(
        dono,
        `INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, data_saida,
                                  posto_graduacao, nome_guerra)
         VALUES ($1, $2, $3, DATE '2025-01-01', $4::date, 'SGT', $2) RETURNING id`,
        [`9${digitos(6)}`, nome, setor, saida],
      ),
    );
  const hash = await gerarHash(SENHA);
  const usuario = async (perfil: string, papel: string, ativo = true, comSenha = true) => {
    const login = `api.${papel}.${s}`;
    const id = await inserir(
      dono,
      "INSERT INTO core.usuario (pessoa_id, login, perfil, ativo) VALUES ($1, $2, $3, $4) RETURNING id",
      [await pessoa(`Usuário ${papel} ${sufixo}`), login, perfil, ativo],
    );
    if (comSenha) {
      await dono.query("INSERT INTO app.credencial (usuario_id, senha_hash) VALUES ($1, $2)", [
        id,
        hash,
      ]);
    }
    return { id, login };
  };

  const estoquista = await usuario("ESTOQUISTA", "estoque", true, false);
  const material = `Rádio de teste ${sufixo}`;
  const materialId = await unico(() =>
    inserir(
      dono,
      `INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, controle,
                                       prazo_devolucao_horas, custo_unitario)
       VALUES ($1, $2, $3, 'UN', 'SERIAL', 4, 100) RETURNING id`,
      [`${letras(3)}-${digitos(4)}`, material, subcategoria],
    ),
  );
  const unidades: { id: number; bmp: string }[] = [];
  for (let i = 0; i < 24; i++) {
    // O BMP é sorteado dentro da tentativa: numa colisão, a nova tentativa usa outro.
    const unidade = await unico(async () => {
      const bmp = `7${digitos(6)}`;
      const id = await inserir(
        dono,
        `SELECT core.registrar_entrada_unidade(
             p_material_tipo_id => $1, p_local_id => $2, p_executado_por => $3,
             p_bmp => $4, p_ocorrida_em => now() - interval '1 day') AS id`,
        [materialId, local, estoquista.id, bmp],
      );
      return { id, bmp };
    });
    unidades.push(unidade);
  }

  const consumo = await unico(() =>
    inserir(
      dono,
      `INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, controle,
                                       custo_unitario)
       VALUES ($1, $2, $3, 'PCT', 'CONSUMO', 5) RETURNING id`,
      [`${letras(3)}-${digitos(4)}`, `Pilha de teste ${sufixo}`, subcategoria],
    ),
  );
  await dono.query(`SELECT core.cadastrar_saldo_consumo($1, $2, 10, 500, $3)`, [
    consumo,
    local,
    estoquista.id,
  ]);
  await dono.query(
    `SELECT core.registrar_entrada_consumo(p_material_tipo_id => $1, p_quantidade => 50,
         p_executado_por => $2, p_ocorrida_em => now() - interval '1 day')`,
    [consumo, estoquista.id],
  );

  return {
    sufixo,
    material,
    materialId,
    unidades,
    consumo: { id: consumo, saldo: 50 },
    local,
    setor,
    categoria,
    subcategoria,
    pessoa: await pessoa(`Maria Recebedora ${sufixo}`),
    pessoa2: await pessoa(`João Recebedor ${sufixo}`),
    transferida: await pessoa(`Pessoa Transferida ${sufixo}`, "2025-06-30"),
    equipamentista: await usuario("EQUIPAMENTISTA", "equip"),
    admin: await usuario("ADMINISTRADOR", "admin"),
    consulta: await usuario("CONSULTA", "consulta"),
    inativo: await usuario("EQUIPAMENTISTA", "inativo", false),
    estoquista: estoquista.id,
  };
}

export async function prepararAmbiente(): Promise<Ambiente> {
  carregarArquivoEnv();
  const config = carregarConfig();
  const dono = criarPool({ ...config.dono, banco: config.bancoDeTeste });
  const api = criarPool({ ...config.banco, banco: config.bancoDeTeste });

  const { rows } = await dono.query<{ tabela: string | null }>(
    "SELECT to_regclass('app.sessao')::text AS tabela",
  );
  if (rows[0]?.tabela == null) {
    await Promise.all([dono.end(), api.end()]);
    throw new Error(
      `O banco ${config.bancoDeTeste} não tem as tabelas da aplicação. ` +
        "Rode antes: python -m almox.migracoes teste",
    );
  }

  const cenario = await criarCenario(dono);
  const servidor = criarApp({
    pool: api,
    cookieSeguro: false,
    limitePorLogin: new LimiteDeTentativas(MAX_FALHAS_LOGIN, 60_000),
    limitePorIp: new LimiteDeTentativas(1_000, 60_000),
  }).listen(0, "127.0.0.1");
  await once(servidor, "listening");
  const { port } = servidor.address() as AddressInfo;

  return {
    url: `http://127.0.0.1:${port}`,
    dono,
    api,
    cenario,
    fechar: async () => {
      servidor.close();
      await Promise.all([dono.end(), api.end()]);
    },
  };
}

export interface Resposta {
  status: number;
  corpo: Record<string, unknown>;
  cabecalhos: Headers;
}

/** Cliente HTTP que guarda o cookie da sessão, como um navegador. */
export class Cliente {
  cookie: string | undefined;

  constructor(private readonly url: string) {}

  async pedir(
    metodo: string,
    caminho: string,
    corpo?: unknown,
    cabecalhos: Record<string, string> = {},
  ): Promise<Resposta> {
    const resposta = await fetch(`${this.url}${caminho}`, {
      method: metodo,
      headers: {
        ...(corpo === undefined ? {} : { "Content-Type": "application/json" }),
        ...(this.cookie === undefined ? {} : { Cookie: this.cookie }),
        ...cabecalhos,
      },
      ...(corpo === undefined
        ? {}
        : { body: typeof corpo === "string" ? corpo : JSON.stringify(corpo) }),
    });
    const setCookie = resposta.headers.get("set-cookie");
    if (setCookie !== null) this.cookie = setCookie.split(";")[0];
    const texto = await resposta.text();
    return {
      status: resposta.status,
      corpo: texto === "" ? {} : (JSON.parse(texto) as Record<string, unknown>),
      cabecalhos: resposta.headers,
    };
  }

  async entrar(login: string, senha = SENHA): Promise<Resposta> {
    return this.pedir("POST", "/api/sessao", { login, senha });
  }
}

export async function entrarComo(url: string, login: string): Promise<Cliente> {
  const cliente = new Cliente(url);
  const resposta = await cliente.entrar(login);
  if (resposta.status !== 200) throw new Error(`login de ${login} falhou: ${resposta.status}`);
  return cliente;
}
