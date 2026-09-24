/** Cabeçalhos de segurança, CSRF, rotas desconhecidas e arquivos estáticos. */
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { type Ambiente, Cliente, entrarComo, prepararAmbiente } from "./apoio.ts";

let amb: Ambiente;
before(async () => {
  amb = await prepararAmbiente();
});
after(async () => {
  await amb.fechar();
});

test("cabeçalhos de segurança na tela e na API; sem X-Powered-By", async () => {
  for (const caminho of ["/", "/api/sessao"]) {
    const r = await fetch(`${amb.url}${caminho}`);
    const csp = r.headers.get("content-security-policy") ?? "";
    assert.match(csp, /default-src 'self'/);
    assert.match(csp, /script-src 'self'(;|$)/); // sem 'unsafe-inline'
    assert.match(csp, /frame-ancestors 'none'/);
    assert.equal(r.headers.get("x-content-type-options"), "nosniff");
    assert.equal(r.headers.get("x-powered-by"), null);
  }
  const api = await fetch(`${amb.url}/api/sessao`);
  assert.equal(api.headers.get("cache-control"), "no-store");
});

test("pedido que altera algo, vindo de outra origem → 403", async () => {
  const cliente = await entrarComo(amb.url, amb.cenario.equipamentista.login);
  const r = await cliente.pedir(
    "POST",
    "/api/retiradas",
    { unidade_id: amb.cenario.unidades[0]?.id, pessoa_id: amb.cenario.pessoa },
    { Origin: "https://site-malicioso.example" },
  );
  assert.equal(r.status, 403);
  assert.equal(r.corpo.codigo, "ORIGEM_PROIBIDA");
});

test("rota desconhecida: 401 sem sessão (não revela o que existe), 404 com sessão", async () => {
  assert.equal((await new Cliente(amb.url).pedir("GET", "/api/admin")).status, 401);
  const cliente = await entrarComo(amb.url, amb.cenario.equipamentista.login);
  assert.equal((await cliente.pedir("GET", "/api/admin")).status, 404);
});

test("arquivos fora da pasta web não são servidos", async () => {
  for (const caminho of [
    "/../.env",
    "/%2e%2e/.env",
    "/..%2f.env",
    "/.env",
    "/%2e%2e/api/src/config.ts",
  ]) {
    const r = await fetch(`${amb.url}${caminho}`);
    const texto = await r.text();
    assert.ok(r.status >= 400, `${caminho} veio ${r.status}`);
    assert.ok(!texto.includes("ALMOX_"), `${caminho} vazou conteúdo`);
  }
});
