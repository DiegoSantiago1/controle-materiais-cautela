/** Busca, cautelas em aberto, retirada e devolução pela API. */
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";
import { type Ambiente, type Cliente, entrarComo, prepararAmbiente } from "./apoio.ts";

let amb: Ambiente;
let equip: Cliente;
let unidadeLivre: () => { id: number; bmp: string };

before(async () => {
  amb = await prepararAmbiente();
  equip = await entrarComo(amb.url, amb.cenario.equipamentista.login);
  // Cada teste pega uma unidade ainda não usada.
  const livres = [...amb.cenario.unidades];
  unidadeLivre = () => {
    const unidade = livres.shift();
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

async function movimentacoes(unidade: number): Promise<{ tipo: string; executado_por: number }[]> {
  const { rows } = await amb.dono.query<{ tipo: string; executado_por: number }>(
    "SELECT tipo, executado_por FROM core.movimentacao WHERE unidade_id = $1 ORDER BY id",
    [unidade],
  );
  return rows;
}

describe("busca", () => {
  test("material sem acento e em minúsculas encontra 'Rádio de teste'", async () => {
    const termo = `radio de teste ${amb.cenario.sufixo.toLowerCase()}`;
    const r = await equip.pedir("GET", `/api/unidades?busca=${encodeURIComponent(termo)}`);
    assert.equal(r.status, 200);
    assert.equal((r.corpo.unidades as unknown[]).length, amb.cenario.unidades.length);
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

  test("pessoa transferida não aparece na busca de quem pode receber", async () => {
    const r = await equip.pedir(
      "GET",
      `/api/pessoas?busca=${encodeURIComponent(amb.cenario.sufixo)}`,
    );
    const ids = (r.corpo.pessoas as { id: number }[]).map((p) => p.id);
    assert.ok(ids.includes(amb.cenario.pessoa));
    assert.ok(!ids.includes(amb.cenario.transferida));
  });

  for (const consulta of ["", "?busca=a", "?busca=a&busca=b", `?busca=${"x".repeat(61)}`]) {
    test(`busca inválida (${consulta || "sem termo"}) → 400`, async () => {
      assert.equal((await equip.pedir("GET", `/api/unidades${consulta}`)).status, 400);
      assert.equal((await equip.pedir("GET", `/api/pessoas${consulta}`)).status, 400);
    });
  }
});

describe("retirada", () => {
  test("abre a cautela; quem executa vem da sessão, não do corpo", async () => {
    const { id } = unidadeLivre();
    const r = await equip.pedir("POST", "/api/retiradas", {
      unidade_id: id,
      pessoa_id: amb.cenario.pessoa,
      finalidade: "Manutenção do gerador",
      executado_por: amb.cenario.estoquista, // tentativa de se passar por outro: ignorada
    });
    assert.equal(r.status, 201);
    const prazoH = (Date.parse(r.corpo.prazo as string) - Date.now()) / 3_600_000;
    assert.ok(prazoH > 3.9 && prazoH <= 4, `prazo de 4 h do material (veio ${prazoH})`);
    assert.equal(await statusDaUnidade(id), "CAUTELADA");
    assert.deepEqual((await movimentacoes(id)).at(-1), {
      tipo: "RETIRADA",
      executado_por: amb.cenario.equipamentista.id,
    });

    const lista = await equip.pedir("GET", "/api/cautelas");
    const cautela = (lista.corpo.cautelas as { unidade_id: number; pessoa_id: number }[]).find(
      (c) => c.unidade_id === id,
    );
    assert.equal(cautela?.pessoa_id, amb.cenario.pessoa);
  });

  test("unidade já cautelada → 409, e nada muda", async () => {
    const { id } = unidadeLivre();
    const corpo = { unidade_id: id, pessoa_id: amb.cenario.pessoa };
    assert.equal((await equip.pedir("POST", "/api/retiradas", corpo)).status, 201);
    const segunda = await equip.pedir("POST", "/api/retiradas", {
      ...corpo,
      pessoa_id: amb.cenario.pessoa2,
    });
    assert.equal(segunda.status, 409);
    assert.equal(segunda.corpo.codigo, "OPERACAO_INCOMPATIVEL");
    assert.equal((await movimentacoes(id)).length, 2); // entrada + uma retirada
  });

  test("pessoa que já saiu da unidade → 409 (regra do banco)", async () => {
    const { id } = unidadeLivre();
    const r = await equip.pedir("POST", "/api/retiradas", {
      unidade_id: id,
      pessoa_id: amb.cenario.transferida,
    });
    assert.equal(r.status, 409);
    assert.equal(r.corpo.codigo, "PESSOA_FORA_DA_UNIDADE");
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
  });

  test("unidade inexistente ou pessoa inexistente → 404", async () => {
    const maior = 2_147_483_647;
    const semUnidade = await equip.pedir("POST", "/api/retiradas", {
      unidade_id: maior,
      pessoa_id: amb.cenario.pessoa,
    });
    assert.equal(semUnidade.status, 404);
    const { id } = unidadeLivre();
    const semPessoa = await equip.pedir("POST", "/api/retiradas", {
      unidade_id: id,
      pessoa_id: maior,
    });
    assert.equal(semPessoa.status, 404);
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
  });

  test("perfil CONSULTA não retira: o BANCO recusa (403) e nada é gravado", async () => {
    const consulta = await entrarComo(amb.url, amb.cenario.consulta.login);
    const { id } = unidadeLivre();
    const r = await consulta.pedir("POST", "/api/retiradas", {
      unidade_id: id,
      pessoa_id: amb.cenario.pessoa,
    });
    assert.equal(r.status, 403);
    assert.equal(r.corpo.codigo, "SEM_PERMISSAO");
    assert.equal((await movimentacoes(id)).length, 1);
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
  });

  const idsHostis: unknown[] = ["1", 1.5, -1, 0, 2_147_483_648, 1e20, null, true, [1], { a: 1 }];
  for (const valor of idsHostis) {
    test(`unidade_id hostil ${JSON.stringify(valor)} → 400 com o nome do campo`, async () => {
      const r = await equip.pedir("POST", "/api/retiradas", {
        unidade_id: valor,
        pessoa_id: amb.cenario.pessoa,
      });
      assert.equal(r.status, 400);
      assert.equal(r.corpo.campo, "unidade_id");
    });
  }

  test("finalidade com HTML é guardada como texto, sem interpretar", async () => {
    const { id } = unidadeLivre();
    const html = '<img src=x onerror="alert(1)">';
    const r = await equip.pedir("POST", "/api/retiradas", {
      unidade_id: id,
      pessoa_id: amb.cenario.pessoa2,
      finalidade: html,
    });
    assert.equal(r.status, 201);
    assert.match(r.cabecalhos.get("content-type") ?? "", /^application\/json/);
    const { rows } = await amb.dono.query(
      "SELECT finalidade FROM core.movimentacao WHERE id = $1",
      [r.corpo.movimentacao_id],
    );
    assert.equal(rows[0]?.finalidade, html);
  });

  test("10 retiradas simultâneas da mesma unidade: exatamente uma passa", async () => {
    const { id } = unidadeLivre();
    const respostas = await Promise.all(
      Array.from({ length: 10 }, (_, i) =>
        equip.pedir("POST", "/api/retiradas", {
          unidade_id: id,
          pessoa_id: i % 2 === 0 ? amb.cenario.pessoa : amb.cenario.pessoa2,
        }),
      ),
    );
    const status = respostas.map((r) => r.status).sort();
    assert.deepEqual(status, [201, ...Array(9).fill(409)]);
    assert.equal((await movimentacoes(id)).filter((m) => m.tipo === "RETIRADA").length, 1);
  });
});

describe("devolução e cautelas vencidas", () => {
  test("BOM: a unidade volta a ficar disponível", async () => {
    const { id } = unidadeLivre();
    await equip.pedir("POST", "/api/retiradas", { unidade_id: id, pessoa_id: amb.cenario.pessoa });
    const r = await equip.pedir("POST", "/api/devolucoes", {
      unidade_id: id,
      pessoa_id: amb.cenario.pessoa,
      estado: "BOM",
    });
    assert.equal(r.status, 201);
    assert.equal(await statusDaUnidade(id), "DISPONIVEL");
    const lista = await equip.pedir("GET", "/api/cautelas");
    const ids = (lista.corpo.cautelas as { unidade_id: number }[]).map((c) => c.unidade_id);
    assert.ok(!ids.includes(id));
  });

  test("AVARIADO exige observação (422); com ela, vai para manutenção", async () => {
    const { id } = unidadeLivre();
    await equip.pedir("POST", "/api/retiradas", { unidade_id: id, pessoa_id: amb.cenario.pessoa });
    const corpo = { unidade_id: id, pessoa_id: amb.cenario.pessoa, estado: "AVARIADO" };
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

  test("devolver 'de' quem não está com a unidade → 409, a cautela continua aberta", async () => {
    // Protege a corrida: a tela mostrava Maria, mas a unidade já está com João.
    const { id } = amb.cenario.unidades[0] ?? { id: 0 };
    const detentor = await amb.dono.query<{ detentor_id: number | null }>(
      "SELECT detentor_id FROM core.unidade_patrimonial WHERE id = $1",
      [id],
    );
    const atual = detentor.rows[0]?.detentor_id;
    assert.equal(atual, amb.cenario.pessoa, "a unidade 0 foi retirada por Maria no 1º teste");
    const r = await equip.pedir("POST", "/api/devolucoes", {
      unidade_id: id,
      pessoa_id: amb.cenario.pessoa2,
      estado: "BOM",
    });
    assert.equal(r.status, 409);
    assert.equal(r.corpo.codigo, "NAO_E_O_DETENTOR");
    assert.equal(await statusDaUnidade(id), "CAUTELADA");
  });

  test("estado fora da lista → 400", async () => {
    const r = await equip.pedir("POST", "/api/devolucoes", {
      unidade_id: 1,
      pessoa_id: 1,
      estado: "OTIMO",
    });
    assert.equal(r.status, 400);
    assert.equal(r.corpo.campo, "estado");
  });

  test("cautela com prazo vencido vem marcada e antes das outras", async () => {
    const { id } = unidadeLivre();
    // Retirada de 10 h atrás (prazo de 4 h): só o dono do banco lança com data passada.
    await amb.dono.query(
      `SELECT core.registrar_retirada_unidade(
           p_unidade_id => $1, p_pessoa_id => $2, p_executado_por => $3,
           p_ocorrida_em => now() - interval '10 hours')`,
      [id, amb.cenario.pessoa2, amb.cenario.equipamentista.id],
    );
    const lista = await equip.pedir("GET", "/api/cautelas");
    const cautelas = lista.corpo.cautelas as { unidade_id: number; vencida: boolean }[];
    const minha = cautelas.findIndex((c) => c.unidade_id === id);
    assert.equal(cautelas[minha]?.vencida, true);
    // ordenadas pelo prazo: nenhuma cautela no prazo aparece antes de uma vencida
    const primeiraNoPrazo = cautelas.findIndex((c) => !c.vencida);
    assert.ok(primeiraNoPrazo === -1 || minha < primeiraNoPrazo);
  });
});
