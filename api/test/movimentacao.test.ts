/** Busca, retirada (por quantidade e por BMP), devolução e posse pela API. */
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";
import { type Ambiente, type Cliente, entrarComo, prepararAmbiente } from "./apoio.ts";

let amb: Ambiente;
let equip: Cliente;
let unidadeLivre: () => { id: number; bmp: string };

before(async () => {
  amb = await prepararAmbiente();
  equip = await entrarComo(amb.url, amb.cenario.equipamentista.login);
  // Cada teste pega uma unidade ainda não usada, do fim da lista: a retirada por quantidade
  // deixa o banco escolher, e ele começa pelas de menor id.
  const livres = [...amb.cenario.unidades];
  unidadeLivre = () => {
    const unidade = livres.pop();
    if (unidade === undefined) throw new Error("cenário sem unidades livres: aumente em apoio.ts");
    return unidade;
  };
});
after(async () => {
  await amb.fechar();
});

async function statusDaUnidade(id: number): Promise<string | undefined> {
  const { rows } = await amb.dono.query<{ status: string }>(
    "SELECT status FROM core.unidade_patrimonial WHERE id = $1",
    [id],
  );
  return rows[0]?.status;
}

async function movimentacoes(
  unidade: number,
): Promise<{ tipo: string; executado_por: number; operacao: string | null }[]> {
  const { rows } = await amb.dono.query<{
    tipo: string;
    executado_por: number;
    operacao: string | null;
  }>(
    "SELECT tipo, executado_por, operacao FROM core.movimentacao WHERE unidade_id = $1 ORDER BY id",
    [unidade],
  );
  return rows;
}

function retirar(cliente: Cliente, unidades: number[], pessoa = amb.cenario.pessoa, extra = {}) {
  return cliente.pedir("POST", "/api/retiradas", {
    pessoa_id: pessoa,
    itens: [{ material_id: amb.cenario.materialId, unidades }],
    ...extra,
  });
}

describe("busca", () => {
  test("material sem acento e em minúsculas encontra 'Rádio de teste'", async () => {
    const termo = `radio de teste ${amb.cenario.sufixo.toLowerCase()}`;
    const r = await equip.pedir("GET", `/api/unidades?busca=${encodeURIComponent(termo)}`);
    assert.equal(r.status, 200);
    assert.equal((r.corpo.unidades as unknown[]).length, 20); // limite da busca
  });

  test("BMP exato encontra a unidade", async () => {
    const { id, bmp } = amb.cenario.unidades[0] ?? { id: 0, bmp: "" };
    const r = await equip.pedir("GET", `/api/unidades?busca=${bmp}`);
    assert.deepEqual(
      (r.corpo.unidades as { id: number }[]).map((u) => u.id),
      [id],
    );
  });

  test("curingas do LIKE são texto: '%' e '_' não devolvem tudo", async () => {
    for (const termo of ["%%", "__", "\\%"]) {
      const r = await equip.pedir("GET", `/api/unidades?busca=${encodeURIComponent(termo)}`);
      assert.equal(r.status, 200);
      assert.deepEqual(r.corpo.unidades, []);
    }
  });

  test("militar transferido não aparece na busca de quem pode receber", async () => {
    const r = await equip.pedir(
      "GET",
      `/api/pessoas?busca=${encodeURIComponent(amb.cenario.sufixo)}`,
    );
    const pessoas = r.corpo.pessoas as { id: number; posto: string; nome_guerra: string }[];
    const ids = pessoas.map((p) => p.id);
    assert.ok(ids.includes(amb.cenario.pessoa));
    assert.ok(!ids.includes(amb.cenario.transferida));
    assert.ok(pessoas.every((p) => p.posto === "SGT" && p.nome_guerra.length > 0));
  });

  test("busca pelo posto e nome de guerra ('sgt maria')", async () => {
    const r = await equip.pedir(
      "GET",
      `/api/pessoas?busca=${encodeURIComponent(`sgt maria recebedora ${amb.cenario.sufixo}`)}`,
    );
    assert.deepEqual(
      (r.corpo.pessoas as { id: number }[]).map((p) => p.id),
      [amb.cenario.pessoa],
    );
  });

  for (const consulta of ["", "?busca=a", "?busca=a&busca=b", `?busca=${"x".repeat(61)}`]) {
    test(`busca inválida (${consulta || "sem termo"}) → 400`, async () => {
      assert.equal((await equip.pedir("GET", `/api/unidades${consulta}`)).status, 400);
      assert.equal((await equip.pedir("GET", `/api/pessoas${consulta}`)).status, 400);
    });
  }
});

describe("retirada", () => {
  test("por BMP: abre a posse; quem entrega vem da sessão, não do corpo", async () => {
    const { id, bmp } = unidadeLivre();
    const r = await retirar(equip, [id], amb.cenario.pessoa, {
      finalidade: "Serviço de dia",
      executado_por: amb.cenario.estoquista, // tentativa de se passar por outro: ignorada
    });
    assert.equal(r.status, 201);
    const itens = r.corpo.itens as { bmps: string[]; quantidade: number; prazo: string }[];
    assert.deepEqual(itens[0]?.bmps, [bmp]);
    const prazoH = (Date.parse(itens[0]?.prazo ?? "") - Date.now()) / 3_600_000;
    assert.ok(prazoH > 3.9 && prazoH <= 4, `prazo de 4 h do material (veio ${prazoH})`);
    assert.equal(await statusDaUnidade(id), "CAUTELADA");
    const ultima = (await movimentacoes(id)).at(-1);
    assert.equal(ultima?.tipo, "RETIRADA");
    assert.equal(ultima?.executado_por, amb.cenario.equipamentista.id);
    assert.equal(ultima?.operacao, r.corpo.operacao);
  });

  test("por quantidade: o banco escolhe as unidades; vários materiais na mesma operação", async () => {
    const r = await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa2,
      itens: [
        { material_id: amb.cenario.materialId, quantidade: 2 },
        { material_id: amb.cenario.consumo.id, quantidade: 4 },
      ],
      estado: "REGULAR",
      observacao: "Marcas de uso na alça",
    });
    assert.equal(r.status, 201);
    const itens = r.corpo.itens as { material_tipo_id: number; quantidade: number }[];
    assert.deepEqual(itens.map((i) => i.quantidade).sort(), [2, 4]);
    const { rows } = await amb.dono.query(
      "SELECT count(*)::int AS n, count(DISTINCT estado_retirada)::int AS estados " +
        "FROM core.movimentacao WHERE operacao = $1 AND controle = 'SERIAL'",
      [r.corpo.operacao],
    );
    assert.deepEqual(rows[0], { n: 2, estados: 1 });
    const saldo = await amb.dono.query(
      "SELECT quantidade FROM core.saldo_consumo WHERE material_tipo_id = $1",
      [amb.cenario.consumo.id],
    );
    assert.equal(saldo.rows[0]?.quantidade, amb.cenario.consumo.saldo - 4);
  });

  test("se um item falha, nada sai (tudo numa transação)", async () => {
    const antes = await amb.dono.query(
      "SELECT quantidade FROM core.saldo_consumo WHERE material_tipo_id = $1",
      [amb.cenario.consumo.id],
    );
    const r = await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa,
      itens: [
        { material_id: amb.cenario.consumo.id, quantidade: 1 },
        { material_id: amb.cenario.materialId, quantidade: 500 }, // não há 500
      ],
    });
    assert.equal(r.status, 409);
    assert.equal(r.corpo.codigo, "ESTOQUE_INSUFICIENTE");
    const depois = await amb.dono.query(
      "SELECT quantidade FROM core.saldo_consumo WHERE material_tipo_id = $1",
      [amb.cenario.consumo.id],
    );
    assert.deepEqual(depois.rows, antes.rows);
  });

  test("estado REGULAR sem observação → 422 (regra do banco)", async () => {
    const { id } = unidadeLivre();
    const r = await retirar(equip, [id], amb.cenario.pessoa, { estado: "REGULAR" });
    assert.equal(r.status, 422);
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
  });

  test("unidade já em posse → 409, e nada muda", async () => {
    const { id } = unidadeLivre();
    assert.equal((await retirar(equip, [id])).status, 201);
    const segunda = await retirar(equip, [id], amb.cenario.pessoa2);
    assert.equal(segunda.status, 409);
    assert.equal(segunda.corpo.codigo, "OPERACAO_INCOMPATIVEL");
    assert.equal((await movimentacoes(id)).length, 2); // entrada + uma retirada
  });

  test("militar que já saiu da unidade → 409 (regra do banco)", async () => {
    const { id } = unidadeLivre();
    const r = await retirar(equip, [id], amb.cenario.transferida);
    assert.equal(r.status, 409);
    assert.equal(r.corpo.codigo, "PESSOA_FORA_DA_UNIDADE");
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
  });

  test("material inexistente → 404; pessoa inexistente → 404", async () => {
    const maior = 2_147_483_647;
    const semMaterial = await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa,
      itens: [{ material_id: maior, quantidade: 1 }],
    });
    assert.equal(semMaterial.status, 404);
    const { id } = unidadeLivre();
    const semPessoa = await retirar(equip, [id], maior);
    assert.equal(semPessoa.status, 404);
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
  });

  test("perfil CONSULTA não retira (403) e nada é gravado", async () => {
    const consulta = await entrarComo(amb.url, amb.cenario.consulta.login);
    const { id } = unidadeLivre();
    const r = await retirar(consulta, [id]);
    assert.equal(r.status, 403);
    assert.equal(r.corpo.codigo, "SEM_PERMISSAO");
    assert.equal((await movimentacoes(id)).length, 1);
  });

  const idsHostis: unknown[] = ["1", 1.5, -1, 0, 2_147_483_648, 1e20, null, true, [1], { a: 1 }];
  for (const valor of idsHostis) {
    test(`pessoa_id hostil ${JSON.stringify(valor)} → 400 com o nome do campo`, async () => {
      const r = await equip.pedir("POST", "/api/retiradas", {
        pessoa_id: valor,
        itens: [{ material_id: amb.cenario.materialId, quantidade: 1 }],
      });
      assert.equal(r.status, 400);
      assert.equal(r.corpo.campo, "pessoa_id");
    });
  }

  const itensHostis: [string, unknown, string][] = [
    ["sem itens", [], "itens"],
    ["itens não é lista", { material_id: 1 }, "itens"],
    [
      "21 itens",
      Array.from({ length: 21 }, (_, i) => ({ material_id: i + 1, quantidade: 1 })),
      "itens",
    ],
    ["quantidade 0", [{ material_id: 1, quantidade: 0 }], "itens[0].quantidade"],
    ["quantidade 501", [{ material_id: 1, quantidade: 501 }], "itens[0].quantidade"],
    ["quantidade texto", [{ material_id: 1, quantidade: "2" }], "itens[0].quantidade"],
    ["unidades vazia", [{ material_id: 1, unidades: [] }], "itens[0].unidades"],
    ["unidade repetida", [{ material_id: 1, unidades: [5, 5] }], "itens[0].unidades"],
    [
      "material repetido",
      [
        { material_id: 1, quantidade: 1 },
        { material_id: 1, quantidade: 2 },
      ],
      "itens",
    ],
  ];
  for (const [nome, itens, campo] of itensHostis) {
    test(`itens hostis (${nome}) → 400 em ${campo}`, async () => {
      const r = await equip.pedir("POST", "/api/retiradas", {
        pessoa_id: amb.cenario.pessoa,
        itens,
      });
      assert.equal(r.status, 400);
      assert.equal(r.corpo.campo, campo);
    });
  }

  test("finalidade com HTML é guardada como texto, sem interpretar", async () => {
    const { id } = unidadeLivre();
    const html = '<img src=x onerror="alert(1)">';
    const r = await retirar(equip, [id], amb.cenario.pessoa2, { finalidade: html });
    assert.equal(r.status, 201);
    assert.match(r.cabecalhos.get("content-type") ?? "", /^application\/json/);
    const { rows } = await amb.dono.query(
      "SELECT finalidade FROM core.movimentacao WHERE operacao = $1",
      [r.corpo.operacao],
    );
    assert.equal(rows[0]?.finalidade, html);
  });

  test("10 retiradas simultâneas da mesma unidade: exatamente uma passa", async () => {
    const { id } = unidadeLivre();
    const respostas = await Promise.all(
      Array.from({ length: 10 }, (_, i) =>
        retirar(equip, [id], i % 2 === 0 ? amb.cenario.pessoa : amb.cenario.pessoa2),
      ),
    );
    const status = respostas.map((r) => r.status).sort();
    assert.deepEqual(status, [201, ...Array(9).fill(409)]);
    assert.equal((await movimentacoes(id)).filter((m) => m.tipo === "RETIRADA").length, 1);
  });
});

describe("devolução e posse", () => {
  test("devolução parcial: quem recebeu fica registrado; o resto continua em posse", async () => {
    const a = unidadeLivre();
    const b = unidadeLivre();
    const retirada = await retirar(equip, [a.id, b.id]);
    assert.equal(retirada.status, 201);

    const admin = await entrarComo(amb.url, amb.cenario.admin.login);
    const r = await admin.pedir("POST", "/api/devolucoes", {
      pessoa_id: amb.cenario.pessoa,
      unidades: [a.id],
      estado: "BOM",
    });
    assert.equal(r.status, 201);
    assert.equal(await statusDaUnidade(a.id), "DISPONIVEL");
    assert.equal(await statusDaUnidade(b.id), "CAUTELADA");
    assert.equal((await movimentacoes(a.id)).at(-1)?.executado_por, amb.cenario.admin.id);

    const posse = await equip.pedir("GET", `/api/posse?pessoa_id=${amb.cenario.pessoa}`);
    const grupo = (
      posse.corpo.grupos as { operacao: string; quantidade: number; entregue_por_guerra: string }[]
    ).find((g) => g.operacao === retirada.corpo.operacao);
    assert.equal(grupo?.quantidade, 1);
    assert.match(grupo?.entregue_por_guerra ?? "", /Usuário equip/);
  });

  test("AVARIADO exige observação (422); com ela, vai para manutenção", async () => {
    const { id } = unidadeLivre();
    await retirar(equip, [id]);
    const corpo = { unidades: [id], pessoa_id: amb.cenario.pessoa, estado: "AVARIADO" };
    const semObservacao = await equip.pedir("POST", "/api/devolucoes", corpo);
    assert.equal(semObservacao.status, 422);
    assert.equal(semObservacao.corpo.codigo, "PARAMETRO_INVALIDO");
    const soEspacos = await equip.pedir("POST", "/api/devolucoes", { ...corpo, observacao: "   " });
    assert.equal(soEspacos.status, 422);

    const r = await equip.pedir("POST", "/api/devolucoes", {
      ...corpo,
      observacao: "Antena quebrada",
    });
    assert.equal(r.status, 201);
    assert.equal(await statusDaUnidade(id), "EM_MANUTENCAO");
  });

  test("devolver 'de' quem não está com a unidade → 409, a posse continua", async () => {
    // Protege a corrida: a tela mostrava Maria, mas a unidade já está com João.
    const { id } = unidadeLivre();
    await retirar(equip, [id], amb.cenario.pessoa);
    const r = await equip.pedir("POST", "/api/devolucoes", {
      unidades: [id],
      pessoa_id: amb.cenario.pessoa2,
      estado: "BOM",
    });
    assert.equal(r.status, 409);
    assert.equal(r.corpo.codigo, "NAO_E_O_DETENTOR");
    assert.equal(await statusDaUnidade(id), "CAUTELADA");
  });

  test("estado fora da lista → 400", async () => {
    const r = await equip.pedir("POST", "/api/devolucoes", {
      unidades: [1],
      pessoa_id: 1,
      estado: "OTIMO",
    });
    assert.equal(r.status, 400);
    assert.equal(r.corpo.campo, "estado");
  });

  test("posse vencida vem marcada e antes das outras", async () => {
    const { id } = unidadeLivre();
    // Retirada de 10 h atrás (prazo de 4 h): só o dono do banco lança com data passada.
    await amb.dono.query(
      `SELECT core.registrar_retirada_unidade(
           p_unidade_id => $1, p_pessoa_id => $2, p_executado_por => $3,
           p_ocorrida_em => now() - interval '10 hours')`,
      [id, amb.cenario.pessoa2, amb.cenario.equipamentista.id],
    );
    const lista = await equip.pedir("GET", "/api/posse");
    const grupos = lista.corpo.grupos as {
      unidades: { id: number }[];
      vencida: boolean;
    }[];
    const minha = grupos.findIndex((g) => g.unidades.some((u) => u.id === id));
    assert.equal(grupos[minha]?.vencida, true);
    const primeiraNoPrazo = grupos.findIndex((g) => !g.vencida);
    assert.ok(primeiraNoPrazo === -1 || minha < primeiraNoPrazo);
  });

  test("o ciclo mostra a retirada e a devolução de cada unidade", async () => {
    const { id } = unidadeLivre();
    const retirada = await retirar(equip, [id]);
    await equip.pedir("POST", "/api/devolucoes", {
      unidades: [id],
      pessoa_id: amb.cenario.pessoa,
      estado: "BOM",
    });
    const r = await equip.pedir("GET", `/api/ciclo?operacao=${retirada.corpo.operacao}`);
    assert.equal(r.status, 200);
    const [item] = r.corpo.itens as {
      retirada: { militar: string; entregue_por: string };
      fechamento: { tipo: string; recebido_por: string } | null;
    }[];
    assert.match(item?.retirada.militar ?? "", /^SGT Maria Recebedora/);
    assert.equal(item?.fechamento?.tipo, "DEVOLUCAO");
    assert.match(item?.fechamento?.recebido_por ?? "", /Usuário equip/);
  });

  test("ciclo com operação inválida ou inexistente → 404", async () => {
    for (const q of ["operacao=abc", "operacao=00000000-0000-0000-0000-000000000000"]) {
      assert.equal((await equip.pedir("GET", `/api/ciclo?${q}`)).status, 404);
    }
    assert.equal((await equip.pedir("GET", "/api/ciclo")).status, 400);
  });
});
