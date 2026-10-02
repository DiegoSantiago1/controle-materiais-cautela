/**
 * Entrar, sair, "quem sou eu" e troca da própria senha. São as únicas rotas que funcionam
 * sem sessão (menos a troca de senha, que exige estar logado).
 */
import { type NextFunction, type Request, type Response, Router } from "express";
import { ErroHttp } from "../erros.ts";
import {
  conferirSenha,
  gastarTempoDeConferencia,
  gerarHash,
  SENHA_MAX,
  SENHA_MIN,
} from "../senha.ts";
import {
  abrirSessao,
  buscarSessao,
  DURACAO_MS,
  encerrarSessao,
  hashDoToken,
  NOME_DO_COOKIE,
  tokenDoPedido,
} from "../sessao.ts";
import * as v from "../validacao.ts";
import { type Dependencias, sessao, usuario } from "./comum.ts";

function senhaInformada(valor: unknown, campo: string): string {
  if (typeof valor !== "string" || valor.length === 0 || valor.length > SENHA_MAX) {
    throw new v.ErroDeValidacao(campo, "Informe a senha.");
  }
  return valor;
}

/** Senha nova: de 10 a 128 caracteres (o tamanho importa mais que a "complexidade"). */
export function senhaNova(valor: unknown, campo = "senha"): string {
  if (typeof valor !== "string" || valor.length < SENHA_MIN || valor.length > SENHA_MAX) {
    throw new v.ErroDeValidacao(
      campo,
      `A senha deve ter de ${SENHA_MIN} a ${SENHA_MAX} caracteres.`,
    );
  }
  return valor;
}

export function rotasDeSessao(dep: Dependencias): Router {
  const { pool } = dep;
  const rotas = Router();

  rotas.post("/sessao", async (req, res) => {
    const corpo = v.objeto(req.body);
    const login = v.texto(corpo.login, "login", 32).toLowerCase();
    const senha = senhaInformada(corpo.senha, "senha");

    const ip = req.socket.remoteAddress ?? "desconhecido";
    const espera = Math.max(
      dep.limitePorLogin.segundosBloqueado(login),
      dep.limitePorIp.segundosBloqueado(ip),
    );
    if (espera > 0) {
      res.setHeader("Retry-After", String(espera));
      throw new ErroHttp(429, "Muitas tentativas. Aguarde alguns minutos.", "MUITAS_TENTATIVAS");
    }

    const { rows } = await pool.query<{ id: number; senha_hash: string }>(
      `SELECT u.id, c.senha_hash
       FROM core.usuario u
       JOIN app.credencial c ON c.usuario_id = u.id
       WHERE u.login = $1 AND u.ativo`,
      [login],
    );
    const encontrado = rows[0];
    let confere = false;
    if (encontrado === undefined) {
      await gastarTempoDeConferencia(senha);
    } else {
      confere = await conferirSenha(senha, encontrado.senha_hash);
    }

    if (encontrado === undefined || !confere) {
      dep.limitePorLogin.registrarFalha(login);
      dep.limitePorIp.registrarFalha(ip);
      // A mesma mensagem para login inexistente e senha errada: não revela quem existe.
      throw new ErroHttp(401, "Login ou senha inválidos.", "CREDENCIAIS_INVALIDAS");
    }

    dep.limitePorLogin.limpar(login);
    const token = await abrirSessao(pool, encontrado.id);
    res.cookie(NOME_DO_COOKIE, token, {
      httpOnly: true,
      sameSite: "strict",
      secure: dep.cookieSeguro,
      maxAge: DURACAO_MS,
      path: "/",
    });
    res.json({ usuario: await buscarSessao(pool, token) });
  });

  // "Quem sou eu?": sem sessão, a resposta é usuario null (200), e não um erro. A tela
  // pergunta isso ao abrir; um 401 aqui apareceria como erro no console a cada visita.
  rotas.get("/sessao", async (req, res) => {
    res.json({ usuario: (await buscarSessao(pool, tokenDoPedido(req))) ?? null });
  });

  rotas.delete("/sessao", async (req, res) => {
    await encerrarSessao(pool, tokenDoPedido(req));
    res.clearCookie(NOME_DO_COOKIE, { path: "/", httpOnly: true, sameSite: "strict" });
    res.status(204).end();
  });

  return rotas;
}

/** Daqui para baixo, tudo exige sessão válida. */
export function exigirSessao(dep: Dependencias) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    const token = tokenDoPedido(req);
    const encontrado = await buscarSessao(dep.pool, token);
    if (encontrado === undefined || token === undefined) {
      throw new ErroHttp(401, "Sessão expirada. Entre de novo.", "SEM_SESSAO");
    }
    res.locals.usuario = encontrado;
    res.locals.tokenHash = hashDoToken(token);
    next();
  };
}

/** Troca da própria senha: exige a atual (quem achar o computador logado não troca). */
export function rotasDaPropriaSenha(dep: Dependencias): Router {
  const rotas = Router();
  rotas.post("/sessao/senha", async (req, res) => {
    const corpo = v.objeto(req.body);
    const atual = senhaInformada(corpo.senha_atual, "senha_atual");
    const nova = senhaNova(corpo.senha_nova, "senha_nova");
    const eu = usuario(res);

    const espera = dep.limitePorLogin.segundosBloqueado(eu.login);
    if (espera > 0) {
      res.setHeader("Retry-After", String(espera));
      throw new ErroHttp(429, "Muitas tentativas. Aguarde alguns minutos.", "MUITAS_TENTATIVAS");
    }
    const { rows } = await dep.pool.query<{ senha_hash: string }>(
      "SELECT senha_hash FROM app.credencial WHERE usuario_id = $1",
      [eu.id],
    );
    const guardada = rows[0]?.senha_hash;
    if (guardada === undefined || !(await conferirSenha(atual, guardada))) {
      dep.limitePorLogin.registrarFalha(eu.login);
      throw new v.ErroDeValidacao("senha_atual", "A senha atual não confere.");
    }
    if (atual === nova) {
      throw new v.ErroDeValidacao("senha_nova", "A senha nova precisa ser diferente da atual.");
    }
    await dep.pool.query("SELECT app.trocar_minha_senha($1, $2)", [
      sessao(res),
      await gerarHash(nova),
    ]);
    res.status(204).end();
  });
  return rotas;
}
