/** Consultas: referências, resumo, estoque (atualizado pelas movimentações) e histórico. */
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";
import { type Ambiente, type Cliente, entrarComo, prepararAmbiente } from "./apoio.ts";

let amb: Ambiente;
let equip: Cliente;

before(async () => {
  amb = await prepararAmbiente();
  equip = await entrarComo(amb.url, amb.cenario.equipamentista.login);
});
after(async () => {
  await amb.fechar();
});

interface Estoque {
  total: number;
  disponivel: number;
  em_posse: number;
  em_manutencao: number;
  indisponivel: number;
}

async function estoque(id: number): Promise<Estoque> {
  const r = await equip.pedir("GET", `/api/estoque/${id}`);
  assert.equal(r.status, 200);
  return r.corpo.material as Estoque;
}

describe("referências e resumo", () => {
  test("postos na ordem hierárquica, setores, locais e categorias com subcategorias", async () => {
    const r = await equip.pedir("GET", "/api/referencias");
    assert.equal(r.status, 200);
    const postos = (r.corpo.postos as { sigla: string }[]).map((p) => p.sigla);
    assert.deepEqual(postos, [
      "S2",
      "S1",
      "CB",
      "SGT",
      "ST",
      "TEN",
      "CAP",
      "MAJ",
      "TEN-CEL",
      "CEL",
    ]);
    const categoria = (
      r.corpo.categorias as { id: number; subcategorias: { id: number }[] }[]
    ).find((c) => c.id === amb.cenario.categoria);
    assert.deepEqual(
      categoria?.subcategorias.map((s) => s.id),
      [amb.cenario.subcategoria],
    );
  });

  test("resumo traz os contadores e as listas", async () => {
    const r = await equip.pedir("GET", "/api/resumo");
    assert.equal(r.status, 200);
    const c = r.corpo.contadores as Record<string, number>;
    for (const chave of [
      "em_posse",
      "vencidas",
      "abaixo_do_minimo",
      "em_manutencao",
      "retiradas_hoje",
    ]) {
      assert.equal(typeof c[chave], "number", chave);
    }
    assert.ok(Array.isArray(r.corpo.vencidas));
    assert.ok(Array.isArray(r.corpo.ultimas));
  });
});

describe("estoque", () => {
  test("retirada e devolução atualizam os números na hora", async () => {
    const id = amb.cenario.materialId;
    const antes = await estoque(id);
    const [a, b] = amb.cenario.unidades;
    const r = await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa,
      itens: [{ material_id: id, unidades: [a?.id, b?.id] }],
    });
    assert.equal(r.status, 201);
    const meio = await estoque(id);
    assert.equal(meio.disponivel, antes.disponivel - 2);
    assert.equal(meio.em_posse, antes.em_posse + 2);
    assert.equal(meio.total, antes.total);

    await equip.pedir("POST", "/api/devolucoes", {
      pessoa_id: amb.cenario.pessoa,
      unidades: [a?.id],
      estado: "AVARIADO",
      observacao: "Tela trincada",
    });
    const depois = await estoque(id);
    assert.equal(depois.em_posse, antes.em_posse + 1);
    assert.equal(depois.em_manutencao, antes.em_manutencao + 1);
    assert.equal(depois.disponivel, antes.disponivel - 2);
  });

  test("retirar mais do que há → 409 e o estoque não fica negativo", async () => {
    const r = await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa,
      itens: [{ material_id: amb.cenario.consumo.id, quantidade: 400 }],
    });
    assert.equal(r.status, 409);
    assert.equal(r.corpo.codigo, "ESTOQUE_INSUFICIENTE");
    assert.ok((await estoque(amb.cenario.consumo.id)).disponivel >= 0);
  });

  test("lista de estoque e material inexistente", async () => {
    const r = await equip.pedir("GET", "/api/estoque");
    assert.equal(r.status, 200);
    assert.ok((r.corpo.materiais as { id: number }[]).some((m) => m.id === amb.cenario.materialId));
    assert.equal((await equip.pedir("GET", "/api/estoque/2147483647")).status, 404);
  });
});

describe("histórico", () => {
  test("agrupa por atendimento e filtra pelo material", async () => {
    const [, , c, d] = amb.cenario.unidades;
    const r = await equip.pedir("POST", "/api/retiradas", {
      pessoa_id: amb.cenario.pessoa2,
      itens: [{ material_id: amb.cenario.materialId, unidades: [c?.id, d?.id] }],
    });
    const lista = await equip.pedir(
      "GET",
      `/api/movimentacoes?material_id=${amb.cenario.materialId}&tipo=RETIRADA`,
    );
    assert.equal(lista.status, 200);
    const linha = (lista.corpo.movimentacoes as { operacao: string; quantidade: number }[]).find(
      (m) => m.operacao === r.corpo.operacao,
    );
    assert.equal(linha?.quantidade, 2);
  });

  test("busca pelo nome de guerra de quem entregou", async () => {
    const termo = encodeURIComponent(`usuario equip ${amb.cenario.sufixo}`);
    const lista = await equip.pedir("GET", `/api/movimentacoes?busca=${termo}`);
    assert.equal(lista.status, 200);
    assert.ok((lista.corpo.movimentacoes as unknown[]).length > 0);
  });

  test("paginação por cursor não repete linha", async () => {
    const primeira = await equip.pedir("GET", "/api/movimentacoes");
    const linhas = primeira.corpo.movimentacoes as { ocorrida_em: string; ultimo_id: number }[];
    const ultima = linhas.at(-1);
    if (!primeira.corpo.tem_mais || ultima === undefined) return; // banco de teste pequeno
    const segunda = await equip.pedir(
      "GET",
      `/api/movimentacoes?antes_em=${encodeURIComponent(ultima.ocorrida_em)}&antes_id=${ultima.ultimo_id}`,
    );
    const ids = new Set(linhas.map((l) => l.ultimo_id));
    for (const l of segunda.corpo.movimentacoes as { ultimo_id: number }[]) {
      assert.ok(!ids.has(l.ultimo_id));
    }
  });

  const filtrosInvalidos = [
    "tipo=QUALQUER",
    "de=2026-13-01",
    "de=ontem",
    "de=2026-10-02&ate=2026-10-01",
    "antes_em=2026-10-01",
    "antes_id=abc",
    "material_id=-1",
    "busca=a&busca=b",
  ];
  for (const filtro of filtrosInvalidos) {
    test(`filtro inválido (${filtro}) → 400`, async () => {
      assert.equal((await equip.pedir("GET", `/api/movimentacoes?${filtro}`)).status, 400);
    });
  }

  test("período por data (faixa do dia inteiro)", async () => {
    const hoje = new Date().toLocaleDateString("sv-SE", { timeZone: "America/Recife" });
    const r = await equip.pedir("GET", `/api/movimentacoes?de=${hoje}&ate=${hoje}`);
    assert.equal(r.status, 200);
    for (const m of r.corpo.movimentacoes as { ocorrida_em: string }[]) {
      const dia = new Date(m.ocorrida_em).toLocaleDateString("sv-SE", {
        timeZone: "America/Recife",
      });
      assert.equal(dia, hoje);
    }
  });
});
