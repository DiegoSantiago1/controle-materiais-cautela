/**
 * Rotas da API. A ordem importa: primeiro as de sessão (entrar, sair, "quem sou eu"),
 * depois a exigência de sessão válida, e só então o resto.
 *
 * Escrita só pelas funções app.* do banco. O usuário do banco que a API usa não tem
 * INSERT, UPDATE nem DELETE em nenhuma tabela do core (migrações 0012 e 0015).
 */
import { Router } from "express";
import { rotasDeAdministracao } from "./admin.ts";
import type { Dependencias } from "./comum.ts";
import { rotasDeConsulta } from "./consultas.ts";
import { rotasDeOperacao } from "./operacao.ts";
import { exigirSessao, rotasDaPropriaSenha, rotasDeSessao } from "./sessao.ts";

export type { Dependencias } from "./comum.ts";

export function criarRotas(dep: Dependencias): Router {
  const rotas = Router();
  rotas.use(rotasDeSessao(dep));
  rotas.use(exigirSessao(dep));
  rotas.use(rotasDaPropriaSenha(dep));
  rotas.use(rotasDeConsulta(dep));
  rotas.use(rotasDeOperacao(dep));
  rotas.use(rotasDeAdministracao(dep));
  return rotas;
}
