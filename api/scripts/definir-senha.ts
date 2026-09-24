/**
 * Define (ou troca) a senha de um usuário no banco da aplicação.
 *
 *   npm run definir-senha -- enzo.04
 *
 * A senha é digitada sem aparecer na tela (ou lida da entrada padrão, se vier por pipe),
 * nunca pela linha de comando: argumentos ficam visíveis na lista de processos e no
 * histórico do terminal. Roda como o dono do banco, porque o usuário da API só lê as
 * credenciais. Trocar a senha encerra as sessões abertas daquele usuário.
 */
import { stdin, stdout } from "node:process";
import { carregarArquivoEnv, carregarConfig } from "../src/config.ts";
import { criarPool } from "../src/db.ts";
import { gerarHash, SENHA_MAX, SENHA_MIN } from "../src/senha.ts";

function lerOculto(pergunta: string): Promise<string> {
  return new Promise((resolve, reject) => {
    stdout.write(pergunta);
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding("utf8");
    let digitado = "";
    const aoDigitar = (tecla: string) => {
      for (const c of tecla) {
        if (c === "\r" || c === "\n") {
          stdin.setRawMode(false);
          stdin.pause();
          stdin.off("data", aoDigitar);
          stdout.write("\n");
          resolve(digitado);
          return;
        }
        if (c === "\u0003") {
          stdin.setRawMode(false);
          reject(new Error("Cancelado."));
          return;
        }
        digitado = c === "\u007f" || c === "\b" ? digitado.slice(0, -1) : digitado + c;
      }
    };
    stdin.on("data", aoDigitar);
  });
}

async function lerDaEntrada(): Promise<string> {
  let texto = "";
  for await (const parte of stdin) texto += parte;
  return texto.split(/\r?\n/)[0] ?? "";
}

async function main(): Promise<number> {
  const login = process.argv[2]?.toLowerCase();
  if (login === undefined || !/^[a-z][a-z0-9._]{2,31}$/.test(login)) {
    console.error("Uso: npm run definir-senha -- <login>");
    return 2;
  }
  carregarArquivoEnv();
  const config = carregarConfig();

  let senha: string;
  if (stdin.isTTY) {
    senha = await lerOculto(`Nova senha para ${login}: `);
    if ((await lerOculto("Repita a senha: ")) !== senha) {
      console.error("As senhas não conferem.");
      return 1;
    }
  } else {
    senha = await lerDaEntrada();
  }
  if (senha.length < SENHA_MIN || senha.length > SENHA_MAX) {
    console.error(`A senha precisa ter de ${SENHA_MIN} a ${SENHA_MAX} caracteres.`);
    return 1;
  }

  const pool = criarPool(config.dono);
  try {
    const cliente = await pool.connect();
    try {
      await cliente.query("BEGIN");
      const { rows } = await cliente.query<{ id: number; perfil: string }>(
        "SELECT id, perfil FROM core.usuario WHERE login = $1 AND ativo",
        [login],
      );
      const usuario = rows[0];
      if (usuario === undefined) {
        await cliente.query("ROLLBACK");
        console.error(`Usuário ativo "${login}" não encontrado em ${config.dono.banco}.`);
        return 1;
      }
      await cliente.query(
        `INSERT INTO app.credencial (usuario_id, senha_hash) VALUES ($1, $2)
         ON CONFLICT (usuario_id) DO UPDATE
         SET senha_hash = EXCLUDED.senha_hash, atualizada_em = now()`,
        [usuario.id, await gerarHash(senha)],
      );
      await cliente.query("DELETE FROM app.sessao WHERE usuario_id = $1", [usuario.id]);
      await cliente.query("COMMIT");
      console.log(`Senha definida para ${login} (perfil ${usuario.perfil}).`);
      return 0;
    } catch (erro) {
      await cliente.query("ROLLBACK");
      throw erro;
    } finally {
      cliente.release();
    }
  } finally {
    await pool.end();
  }
}

process.exitCode = await main();
