/** Administração pela API: permissões por perfil, cadastros, usuários, senhas e auditoria. */
import assert from "node:assert/strict";
import { randomInt } from "node:crypto";
import { after, before, describe, test } from "node:test";
import {
  type Ambiente,
  type Cliente,
  entrarComo,
  Cliente as NovoCliente,
  prepararAmbiente,
} from "./apoio.ts";

let amb: Ambiente;
let admin: Cliente;
let equip: Cliente;

before(async () => {
  amb = await prepararAmbiente();
  admin = await entrarComo(amb.url, amb.cenario.admin.login);
  equip = await entrarComo(amb.url, amb.cenario.equipamentista.login);
});
after(async () => {
  await amb.fechar();
});

const matricula = () => `5${String(randomInt(1_000_000)).padStart(6, "0")}`;

async function auditoria(
  entidade: string,
  id: number,
): Promise<{ acao: string; executado_por: number }[]> {
  const { rows } = await amb.dono.query<{ acao: string; executado_por: number }>(
    "SELECT acao, executado_por FROM core.auditoria WHERE entidade = $1 AND entidade_id = $2 ORDER BY id",
    [entidade, id],
  );
  return rows;
}

describe("permissões", () => {
  const rotasDeAdministrador: [string, string][] = [
    ["POST", "/api/categorias"],
    ["PATCH", "/api/categorias/1"],
    ["POST", "/api/subcategorias"],
    ["PATCH", "/api/subcategorias/1"],
    ["POST", "/api/materiais"],
    ["PUT", "/api/materiais/1"],
    ["POST", "/api/militares"],
    ["PUT", "/api/militares/1"],
    ["POST", "/api/militares/1/saida"],
    ["GET", "/api/usuarios"],
    ["POST", "/api/usuarios"],
    ["PATCH", "/api/usuarios/1"],
    ["POST", "/api/usuarios/1/senha"],
    ["GET", "/api/auditoria"],
  ];
  for (const [metodo, caminho] of rotasDeAdministrador) {
    test(`equipamentista: ${metodo} ${caminho} → 403`, async () => {
      const r = await equip.pedir(metodo, caminho, metodo === "GET" ? undefined : {});
      assert.equal(r.status, 403);
      assert.equal(r.corpo.codigo, "SEM_PERMISSAO");
    });
  }

  for (const [metodo, caminho] of [
    ["POST", "/api/materiais/1/entradas"],
    ["POST", "/api/materiais/1/ajuste"],
    ["POST", "/api/unidades/1/situacao"],
  ] as const) {
    test(`equipamentista não dá entrada nem ajusta: ${caminho} → 403`, async () => {
      assert.equal((await equip.pedir(metodo, caminho, {})).status, 403);
    });
  }

  test("sem sessão, toda rota de administrador → 401", async () => {
    const anonimo = new NovoCliente(amb.url);
    for (const [metodo, caminho] of rotasDeAdministrador) {
      const r = await anonimo.pedir(metodo, caminho, metodo === "GET" ? undefined : {});
      assert.equal(r.status, 401, `${metodo} ${caminho}`);
    }
  });

  test("id da rota hostil → 404 (não chega ao banco)", async () => {
    for (const id of ["0", "-1", "1.5", "abc", "99999999999", "1e3"]) {
      assert.equal((await admin.pedir("PUT", `/api/materiais/${id}`, {})).status, 404, id);
    }
  });
});

describe("catálogo", () => {
  test("categoria, subcategoria e material novos; equipamentista vê no estoque", async () => {
    const sufixo = amb.cenario.sufixo;
    const categoria = await admin.pedir("POST", "/api/categorias", {
      nome: `Comunicação ${sufixo}`,
    });
    assert.equal(categoria.status, 201);
    const sub = await admin.pedir("POST", "/api/subcategorias", {
      categoria_id: categoria.corpo.id,
      nome: "Rádios portáteis",
    });
    assert.equal(sub.status, 201);
    const material = await admin.pedir("POST", "/api/materiais", {
      nome: `Rádio HT ${sufixo}`,
      subcategoria_id: sub.corpo.id,
      controle: "SERIAL",
      prazo_devolucao_horas: 12,
      estoque_minimo: 2,
      custo_unitario: 1500.5,
    });
    assert.equal(material.status, 201);
    const id = material.corpo.id as number;

    const entrada = await admin.pedir("POST", `/api/materiais/${id}/entradas`, {
      quantidade: 3,
      local_id: amb.cenario.local,
      documento: "NF 42",
    });
    assert.equal(entrada.status, 201);
    assert.equal((entrada.corpo.bmps as string[]).length, 3);

    const estoque = await equip.pedir("GET", `/api/estoque/${id}`);
    assert.equal(estoque.status, 200);
    const m = estoque.corpo.material as { total: number; disponivel: number; situacao: string };
    assert.deepEqual([m.total, m.disponivel, m.situacao], [3, 3, "NORMAL"]);
    assert.equal((estoque.corpo.unidades as unknown[]).length, 3);
    assert.deepEqual(
      (await auditoria("MATERIAL", id)).map((a) => [a.acao, a.executado_por]),
      [["CADASTRAR", amb.cenario.admin.id]],
    );
  });

  test("nome repetido → 409 DUPLICADO; valores inválidos → 400 com o campo", async () => {
    const nome = `Categoria Única ${amb.cenario.sufixo}`;
    assert.equal((await admin.pedir("POST", "/api/categorias", { nome })).status, 201);
    const repetida = await admin.pedir("POST", "/api/categorias", { nome: nome.toUpperCase() });
    assert.equal(repetida.status, 409);
    assert.equal(repetida.corpo.codigo, "DUPLICADO");

    const casos: [Record<string, unknown>, string][] = [
      [{ controle: "OUTRO" }, "controle"],
      [{ controle: "SERIAL", prazo_devolucao_horas: 0 }, "prazo_devolucao_horas"],
      [{ controle: "SERIAL", custo_unitario: -1 }, "custo_unitario"],
      [{ controle: "SERIAL", custo_unitario: 1.234 }, "custo_unitario"],
      [{ controle: "SERIAL", nome: "" }, "nome"],
      [{ controle: "SERIAL", subcategoria_id: "1" }, "subcategoria_id"],
      [{ controle: "CONSUMO", unidade_medida: "TONELADA" }, "unidade_medida"],
    ];
    for (const [extra, campo] of casos) {
      const r = await admin.pedir("POST", "/api/materiais", {
        nome: `Material ${campo} ${amb.cenario.sufixo}`,
        subcategoria_id: amb.cenario.subcategoria,
        ...extra,
      });
      assert.equal(r.status, 400, campo);
      assert.equal(r.corpo.campo, campo);
    }
  });

  test("consumo sem mínimo/máximo → 422 (regra do banco)", async () => {
    const r = await admin.pedir("POST", "/api/materiais", {
      nome: `Fita ${amb.cenario.sufixo}`,
      subcategoria_id: amb.cenario.subcategoria,
      controle: "CONSUMO",
      unidade_medida: "ROLO",
      local_id: amb.cenario.local,
    });
    assert.equal(r.status, 422);
  });

  test("editar material: desativado não recebe entrada", async () => {
    const criado = await admin.pedir("POST", "/api/materiais", {
      nome: `Tonfa ${amb.cenario.sufixo}`,
      subcategoria_id: amb.cenario.subcategoria,
      controle: "SERIAL",
      prazo_devolucao_horas: 12,
    });
    const id = criado.corpo.id as number;
    const editado = await admin.pedir("PUT", `/api/materiais/${id}`, {
      nome: `Tonfa ${amb.cenario.sufixo}`,
      subcategoria_id: amb.cenario.subcategoria,
      prazo_devolucao_horas: 24,
      estoque_minimo: 4,
      custo_unitario: 180,
      descricao: "Polímero",
      ativo: false,
    });
    assert.equal(editado.status, 204);
    const entrada = await admin.pedir("POST", `/api/materiais/${id}/entradas`, {
      quantidade: 1,
      local_id: amb.cenario.local,
    });
    assert.equal(entrada.status, 409);
  });

  test("entrada e ajuste de consumo", async () => {
    const id = amb.cenario.consumo.id;
    const antes = await admin.pedir("GET", `/api/estoque/${id}`);
    const saldo = (antes.corpo.material as { disponivel: number }).disponivel;
    assert.equal(
      (await admin.pedir("POST", `/api/materiais/${id}/entradas`, { quantidade: 10 })).status,
      201,
    );
    const ajuste = await admin.pedir("POST", `/api/materiais/${id}/ajuste`, {
      quantidade_contada: saldo + 7,
      justificativa: "Inventário mensal",
    });
    assert.equal(ajuste.status, 201);
    const depois = await admin.pedir("GET", `/api/estoque/${id}`);
    assert.equal((depois.corpo.material as { disponivel: number }).disponivel, saldo + 7);
  });

  test("mudança de situação: manutenção e volta", async () => {
    const unidade = amb.cenario.unidades.at(-1)?.id ?? 0;
    const ida = await admin.pedir("POST", `/api/unidades/${unidade}/situacao`, {
      status: "EM_MANUTENCAO",
      justificativa: "Bateria estufada",
    });
    assert.equal(ida.status, 201);
    const semMotivo = await admin.pedir("POST", `/api/unidades/${unidade}/situacao`, {
      status: "DISPONIVEL",
      justificativa: " ",
    });
    assert.equal(semMotivo.status, 400);
    const proibida = await admin.pedir("POST", `/api/unidades/${unidade}/situacao`, {
      status: "BAIXADA",
      justificativa: "Direto para baixa",
    });
    assert.equal(proibida.status, 409);
    assert.equal(proibida.corpo.codigo, "TRANSICAO_PROIBIDA");
  });
});

describe("militares e usuários", () => {
  test("cadastro do militar, usuário com senha, login dele e troca de perfil", async () => {
    const guerra = `Novato ${amb.cenario.sufixo}`;
    const militar = await admin.pedir("POST", "/api/militares", {
      matricula: matricula(),
      nome: `João Novato ${amb.cenario.sufixo}`,
      nome_guerra: guerra,
      posto: "S2",
      setor_id: amb.cenario.setor,
    });
    assert.equal(militar.status, 201);
    const repetido = await admin.pedir("POST", "/api/militares", {
      matricula: matricula(),
      nome: "Outro",
      nome_guerra: guerra.toUpperCase(),
      posto: "S1",
      setor_id: amb.cenario.setor,
    });
    assert.equal(repetido.status, 409);

    const login = `novato.${amb.cenario.sufixo.toLowerCase()}`;
    const senhaCurta = await admin.pedir("POST", "/api/usuarios", {
      pessoa_id: militar.corpo.id,
      login,
      perfil: "EQUIPAMENTISTA",
      senha: "123",
    });
    assert.equal(senhaCurta.status, 400);
    assert.equal(senhaCurta.corpo.campo, "senha");

    const usuario = await admin.pedir("POST", "/api/usuarios", {
      pessoa_id: militar.corpo.id,
      login,
      perfil: "EQUIPAMENTISTA",
      senha: "senha-do-novato-1",
    });
    assert.equal(usuario.status, 201);
    const novato = new NovoCliente(amb.url);
    assert.equal((await novato.entrar(login, "senha-do-novato-1")).status, 200);
    assert.equal((await novato.pedir("GET", "/api/posse")).status, 200);

    // Rebaixado a CONSULTA: a sessão aberta cai na hora.
    const id = usuario.corpo.id as number;
    const patch = await admin.pedir("PATCH", `/api/usuarios/${id}`, {
      perfil: "CONSULTA",
      ativo: true,
    });
    assert.equal(patch.status, 204);
    assert.equal((await novato.pedir("GET", "/api/posse")).status, 401);
  });

  test("administrador não tira o próprio acesso", async () => {
    const r = await admin.pedir("PATCH", `/api/usuarios/${amb.cenario.admin.id}`, {
      perfil: "EQUIPAMENTISTA",
      ativo: true,
    });
    assert.equal(r.status, 422);
    assert.equal(r.corpo.codigo, "PARAMETRO_INVALIDO");
  });

  test("senha redefinida pelo administrador derruba as sessões do usuário", async () => {
    const vitima = await entrarComo(amb.url, amb.cenario.consulta.login);
    assert.equal((await vitima.pedir("GET", "/api/posse")).status, 200);
    const r = await admin.pedir("POST", `/api/usuarios/${amb.cenario.consulta.id}/senha`, {
      senha: "nova-senha-123",
    });
    assert.equal(r.status, 204);
    assert.equal((await vitima.pedir("GET", "/api/posse")).status, 401);
    assert.equal(
      (await new NovoCliente(amb.url).entrar(amb.cenario.consulta.login, "nova-senha-123")).status,
      200,
    );
  });

  test("saída do militar com material em posse → 409", async () => {
    const unidade = amb.cenario.unidades[0]?.id ?? 0;
    await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa,
      itens: [{ material_id: amb.cenario.materialId, unidades: [unidade] }],
    });
    const r = await admin.pedir("POST", `/api/militares/${amb.cenario.pessoa}/saida`, {
      data_saida: new Date().toISOString().slice(0, 10),
    });
    assert.equal(r.status, 409);
  });

  test("data inválida → 400", async () => {
    for (const data of ["2026-02-30", "02/10/2026", "", 20261002]) {
      const r = await admin.pedir("POST", `/api/militares/${amb.cenario.pessoa2}/saida`, {
        data_saida: data,
      });
      assert.equal(r.status, 400, String(data));
    }
  });

  test("auditoria lista quem fez o quê", async () => {
    const r = await admin.pedir("GET", "/api/auditoria");
    assert.equal(r.status, 200);
    const registros = r.corpo.registros as { acao: string; executor_guerra: string }[];
    assert.ok(registros.length > 0);
    assert.ok(registros.some((x) => x.acao === "DEFINIR_SENHA"));
  });

  test("lista de usuários não expõe hash de senha", async () => {
    const r = await admin.pedir("GET", "/api/usuarios");
    assert.equal(r.status, 200);
    assert.ok(!JSON.stringify(r.corpo).includes("scrypt$"));
  });
});

describe("própria senha", () => {
  test("troca exige a senha atual; a sessão continua, as outras caem", async () => {
    const outra = await entrarComo(amb.url, amb.cenario.equipamentista.login);
    const errada = await equip.pedir("POST", "/api/sessao/senha", {
      senha_atual: "errada-123456",
      senha_nova: "senha-nova-do-equip",
    });
    assert.equal(errada.status, 400);
    assert.equal(errada.corpo.campo, "senha_atual");
    const curta = await equip.pedir("POST", "/api/sessao/senha", {
      senha_atual: "senha-de-teste-123",
      senha_nova: "curta",
    });
    assert.equal(curta.status, 400);

    const ok = await equip.pedir("POST", "/api/sessao/senha", {
      senha_atual: "senha-de-teste-123",
      senha_nova: "senha-nova-do-equip",
    });
    assert.equal(ok.status, 204);
    assert.equal((await equip.pedir("GET", "/api/posse")).status, 200);
    assert.equal((await outra.pedir("GET", "/api/posse")).status, 401);
  });
});

describe("dados de acesso", () => {
  test("lista de militares: login e perfil só para o administrador", async () => {
    const comoEquip = await equip.pedir("GET", "/api/militares");
    assert.equal(comoEquip.status, 200);
    const militares = comoEquip.corpo.militares as {
      login: string | null;
      perfil: string | null;
    }[];
    assert.ok(militares.length > 0);
    assert.ok(militares.every((m) => m.login === null && m.perfil === null));

    const comoAdmin = await admin.pedir("GET", "/api/militares");
    const comLogin = (comoAdmin.corpo.militares as { login: string | null }[]).filter(
      (m) => m.login,
    );
    assert.ok(comLogin.length > 0);
  });
});
