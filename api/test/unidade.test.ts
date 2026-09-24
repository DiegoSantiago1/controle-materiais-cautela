/** Testes unitários (sem banco): validação, limite de tentativas, senha e configuração. */
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { carregarConfig, ErroDeConfiguracao } from "../src/config.ts";
import { LimiteDeTentativas } from "../src/limite.ts";
import { conferirSenha, gerarHash } from "../src/senha.ts";
import * as v from "../src/validacao.ts";

describe("validação", () => {
  test("id aceita só inteiro positivo dentro do integer do PostgreSQL", () => {
    assert.equal(v.id(1, "x"), 1);
    assert.equal(v.id(2_147_483_647, "x"), 2_147_483_647);
    for (const ruim of [0, -1, 1.5, 2_147_483_648, Number.NaN, Infinity, "1", null, true]) {
      assert.throws(() => v.id(ruim, "x"), v.ErroDeValidacao, `aceitou ${String(ruim)}`);
    }
  });

  test("texto: apara espaços, recusa controle e tamanho; opcional vazio vira null", () => {
    assert.equal(v.texto("  a b  ", "x", 10), "a b");
    assert.equal(v.texto("linha 1\nlinha 2\ttab", "x", 50), "linha 1\nlinha 2\ttab");
    assert.throws(() => v.texto("a\u0000b", "x", 10), v.ErroDeValidacao);
    assert.throws(() => v.texto("a\u001bb", "x", 10), v.ErroDeValidacao);
    assert.throws(() => v.texto("abcdef", "x", 5), v.ErroDeValidacao);
    assert.equal(v.textoOpcional(undefined, "x", 5), null);
    assert.equal(v.textoOpcional("   ", "x", 5), null);
  });

  test("escaparLike trata %, _ e barra como texto", () => {
    assert.equal(v.escaparLike("50%_a\\b"), "50\\%\\_a\\\\b");
  });
});

describe("limite de tentativas", () => {
  test("bloqueia no limite e libera quando a janela vence", () => {
    let agora = 0;
    const limite = new LimiteDeTentativas(3, 60_000, () => agora);
    limite.registrarFalha("a");
    limite.registrarFalha("a");
    assert.equal(limite.segundosBloqueado("a"), 0);
    limite.registrarFalha("a");
    assert.equal(limite.segundosBloqueado("a"), 60);
    assert.equal(limite.segundosBloqueado("b"), 0); // chaves independentes
    agora = 59_000;
    assert.equal(limite.segundosBloqueado("a"), 1);
    agora = 60_000;
    assert.equal(limite.segundosBloqueado("a"), 0);
  });

  test("sucesso zera a contagem", () => {
    const limite = new LimiteDeTentativas(2, 60_000, () => 0);
    limite.registrarFalha("a");
    limite.limpar("a");
    limite.registrarFalha("a");
    assert.equal(limite.segundosBloqueado("a"), 0);
  });
});

describe("senha", () => {
  test("hash confere com a senha certa e não com outra; sal diferente a cada vez", async () => {
    const [h1, h2] = await Promise.all([
      gerarHash("minha senha boa"),
      gerarHash("minha senha boa"),
    ]);
    assert.notEqual(h1, h2);
    assert.match(h1, /^scrypt\$131072\$8\$1\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{43}$/);
    assert.equal(await conferirSenha("minha senha boa", h1), true);
    assert.equal(await conferirSenha("minha senha boA", h1), false);
    assert.equal(await conferirSenha("", h1), false);
  });

  test("hash adulterado com custo absurdo é recusado sem calcular (não trava o servidor)", async () => {
    const h = await gerarHash("x".repeat(10));
    const partes = h.split("$");
    const absurdo = ["scrypt", String(2 ** 30), ...partes.slice(2)].join("$");
    const inicio = performance.now();
    assert.equal(await conferirSenha("x".repeat(10), absurdo), false);
    assert.ok(performance.now() - inicio < 50);
    assert.equal(await conferirSenha("x", "texto-puro"), false);
  });
});

describe("configuração", () => {
  const valido = {
    ALMOX_DB_HOST: "127.0.0.1",
    ALMOX_DB_PORT: "5432",
    ALMOX_DB_NAME: "almoxarifado",
    ALMOX_DB_NAME_TESTE: "almoxarifado_teste",
    ALMOX_DB_NAME_APP: "almoxarifado_app",
    ALMOX_DB_USER: "almox",
    ALMOX_DB_PASSWORD: "s",
    ALMOX_APP_USER: "almox_api",
    ALMOX_APP_PASSWORD: "s2",
  };

  test("a API conecta como o usuário da aplicação, no banco da aplicação", () => {
    const config = carregarConfig(valido);
    assert.equal(config.banco.usuario, "almox_api");
    assert.equal(config.banco.banco, "almoxarifado_app");
    assert.equal(config.portaHttp, 3334);
    assert.equal(config.cookieSeguro, false);
  });

  for (const [nome, alteracao] of [
    ["banco da aplicação = banco das análises", { ALMOX_DB_NAME_APP: "almoxarifado" }],
    ["banco da aplicação = banco de testes", { ALMOX_DB_NAME_APP: "almoxarifado_teste" }],
    ["usuário da API = dono do banco", { ALMOX_APP_USER: "almox" }],
    ["senha da API ausente", { ALMOX_APP_PASSWORD: "" }],
    ["identificador com injeção", { ALMOX_APP_USER: "x; DROP ROLE almox" }],
    ["porta inválida", { ALMOX_API_PORT: "99999" }],
    ["cookie seguro com valor estranho", { ALMOX_API_COOKIE_SEGURO: "talvez" }],
  ] as const) {
    test(`recusa: ${nome}`, () => {
      assert.throws(() => carregarConfig({ ...valido, ...alteracao }), ErroDeConfiguracao);
    });
  }
});
