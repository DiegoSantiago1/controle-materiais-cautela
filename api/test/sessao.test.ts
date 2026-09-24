/** Login, sessão e logout, incluindo força bruta e pedidos hostis. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { after, before, describe, test } from "node:test";
import { type Ambiente, Cliente, entrarComo, MAX_FALHAS_LOGIN, prepararAmbiente } from "./apoio.ts";

let amb: Ambiente;
before(async () => {
  amb = await prepararAmbiente();
});
after(async () => {
  await amb.fechar();
});

describe("login", () => {
  test("com a senha certa: cookie seguro e dados do usuário, sem nada sensível", async () => {
    const cliente = new Cliente(amb.url);
    const r = await cliente.entrar(amb.cenario.equipamentista.login);
    assert.equal(r.status, 200);
    assert.deepEqual(Object.keys(r.corpo.usuario as object).sort(), [
      "id",
      "login",
      "nome",
      "perfil",
    ]);
    assert.equal((r.corpo.usuario as { perfil: string }).perfil, "EQUIPAMENTISTA");

    const cookie = r.cabecalhos.get("set-cookie") ?? "";
    assert.match(cookie, /^almox_sessao=[A-Za-z0-9_-]{43};/);
    assert.match(cookie, /HttpOnly/);
    assert.match(cookie, /SameSite=Strict/);
    assert.match(cookie, /Path=\//);
  });

  test("o banco guarda só o hash do token, nunca o token", async () => {
    const cliente = await entrarComo(amb.url, amb.cenario.equipamentista.login);
    const token = cliente.cookie?.split("=")[1] ?? "";
    const { rows } = await amb.dono.query<{ token_hash: Buffer }>(
      "SELECT token_hash FROM app.sessao WHERE usuario_id = $1",
      [amb.cenario.equipamentista.id],
    );
    const esperado = createHash("sha256").update(token).digest();
    assert.ok(rows.some((l) => l.token_hash.equals(esperado)));
    assert.ok(rows.every((l) => !l.token_hash.toString("utf8").includes(token)));
  });

  test("login é aceito com maiúsculas (é o mesmo usuário)", async () => {
    const r = await new Cliente(amb.url).entrar(amb.cenario.equipamentista.login.toUpperCase());
    assert.equal(r.status, 200);
  });

  test("senha errada e login inexistente dão a MESMA resposta", async () => {
    // (equipamentista, e não consulta: a falha conta para o bloqueio do teste seguinte, e
    // o login certo do equipamentista, nos outros testes, zera a contagem)
    const errada = await new Cliente(amb.url).entrar(
      amb.cenario.equipamentista.login,
      "senha-errada-000",
    );
    const inexistente = await new Cliente(amb.url).entrar("ninguem.existe", "qualquer-senha-00");
    assert.equal(errada.status, 401);
    assert.deepEqual(errada.corpo, inexistente.corpo);
    assert.equal(errada.cabecalhos.get("set-cookie"), null);
  });

  test("usuário desativado não entra, mesmo com a senha certa", async () => {
    const r = await new Cliente(amb.url).entrar(amb.cenario.inativo.login);
    assert.equal(r.status, 401);
  });

  test(`depois de ${MAX_FALHAS_LOGIN} falhas o login bloqueia, até com a senha certa`, async () => {
    const login = amb.cenario.consulta.login;
    for (let i = 0; i < MAX_FALHAS_LOGIN; i++) {
      assert.equal((await new Cliente(amb.url).entrar(login, `errada-${i}-xxxxx`)).status, 401);
    }
    const bloqueado = await new Cliente(amb.url).entrar(login);
    assert.equal(bloqueado.status, 429);
    assert.ok(Number(bloqueado.cabecalhos.get("retry-after")) > 0);
  });

  const hostis: [string, unknown, number][] = [
    ["corpo não JSON", "login=a&senha=b", 400],
    ["lista em vez de objeto", ["a", "b"], 400],
    ["login numérico", { login: 123, senha: "x" }, 400],
    ["senha ausente", { login: "api.x" }, 400],
    ["senha enorme", { login: "api.x", senha: "a".repeat(129) }, 400],
    ["login com caractere nulo", { login: "api\u0000x", senha: "x" }, 400],
    ["injeção de SQL no login", { login: "' OR '1'='1", senha: "' OR '1'='1" }, 401],
    ["corpo grande demais", { login: "a", senha: "b".repeat(20_000) }, 413],
  ];
  for (const [nome, corpo, status] of hostis) {
    test(`pedido hostil: ${nome} → ${status}`, async () => {
      const r = await new Cliente(amb.url).pedir("POST", "/api/sessao", corpo);
      assert.equal(r.status, status);
      assert.equal(typeof r.corpo.erro, "string");
    });
  }

  test("formulário comum (não JSON) é recusado: proteção contra CSRF", async () => {
    const r = await new Cliente(amb.url).pedir("POST", "/api/sessao", "login=a&senha=b", {
      "Content-Type": "application/x-www-form-urlencoded",
    });
    assert.equal(r.status, 415);
  });
});

describe("sessão", () => {
  test("sem cookie, ou com cookie inventado, não há sessão", async () => {
    for (const cookie of [
      undefined,
      "almox_sessao=inventado",
      `almox_sessao=${"A".repeat(43)}`,
      "almox_sessao=' OR 1=1 --",
    ]) {
      const cliente = new Cliente(amb.url);
      cliente.cookie = cookie;
      assert.deepEqual((await cliente.pedir("GET", "/api/sessao")).corpo, { usuario: null });
      assert.equal((await cliente.pedir("GET", "/api/cautelas")).status, 401);
    }
  });

  test("sair apaga a sessão no banco: o cookie antigo deixa de valer", async () => {
    const cliente = await entrarComo(amb.url, amb.cenario.equipamentista.login);
    const antigo = cliente.cookie;
    assert.notEqual((await cliente.pedir("GET", "/api/sessao")).corpo.usuario, null);
    const saida = await cliente.pedir("DELETE", "/api/sessao");
    assert.equal(saida.status, 204);
    const copia = new Cliente(amb.url);
    copia.cookie = antigo;
    assert.equal((await copia.pedir("GET", "/api/cautelas")).status, 401);
    assert.deepEqual((await copia.pedir("GET", "/api/sessao")).corpo, { usuario: null });
  });

  test("sessão vencida não vale", async () => {
    const cliente = await entrarComo(amb.url, amb.cenario.equipamentista.login);
    const token = cliente.cookie?.split("=")[1] ?? "";
    await amb.dono.query(
      `UPDATE app.sessao SET criada_em = now() - interval '9 hours',
                             expira_em = now() - interval '1 hour'
       WHERE token_hash = $1`,
      [createHash("sha256").update(token).digest()],
    );
    assert.equal((await cliente.pedir("GET", "/api/cautelas")).status, 401);
    assert.deepEqual((await cliente.pedir("GET", "/api/sessao")).corpo, { usuario: null });
  });

  test("usuário desativado perde o acesso na hora, com a sessão aberta", async () => {
    const { equipamentista } = amb.cenario; // o consulta ficou bloqueado pela força bruta
    const cliente = await entrarComo(amb.url, equipamentista.login);
    assert.equal((await cliente.pedir("GET", "/api/cautelas")).status, 200);
    await amb.dono.query("UPDATE core.usuario SET ativo = false WHERE id = $1", [
      equipamentista.id,
    ]);
    try {
      assert.equal((await cliente.pedir("GET", "/api/cautelas")).status, 401);
    } finally {
      await amb.dono.query("UPDATE core.usuario SET ativo = true WHERE id = $1", [
        equipamentista.id,
      ]);
    }
  });
});
