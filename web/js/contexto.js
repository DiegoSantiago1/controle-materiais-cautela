// Estado compartilhado entre as páginas: quem está logado, as listas de referência (postos,
// setores, locais, categorias) e as permissões de cada perfil.
//
// As permissões aqui só decidem o que APARECE na tela. Quem decide o que pode ser FEITO é a
// API (403) e, depois dela, a função do banco (ALM05).

import { ErroApi, pedir } from "./api.js";
import { avisar, mostrarErroCampo } from "./ui.js";

export const OPERACIONAIS = ["ADMINISTRADOR", "ESTOQUISTA", "EQUIPAMENTISTA"];
export const GESTAO_DE_ESTOQUE = ["ADMINISTRADOR", "ESTOQUISTA"];
export const ADMINISTRACAO = ["ADMINISTRADOR"];

export const contexto = {
  usuario: null,
  referencias: null,
  aoSessaoExpirada: () => {},
};

export const pode = (perfis) =>
  Boolean(contexto.usuario && perfis.includes(contexto.usuario.perfil));

export async function referencias(recarregar = false) {
  if (!contexto.referencias || recarregar) {
    contexto.referencias = await pedir("GET", "/referencias");
  }
  return contexto.referencias;
}

export function irPara(rota, parametros = {}) {
  const busca = new URLSearchParams(
    Object.entries(parametros).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  ).toString();
  const destino = `#/${rota}${busca ? `?${busca}` : ""}`;
  if (location.hash === destino) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = destino;
}

/**
 * Erro de um pedido: sessão vencida volta para a tela de entrada; erro de campo (400 com
 * `campo`) aparece embaixo do campo, se o formulário tiver; o resto vira um aviso.
 */
export function tratarErro(erro, formulario) {
  if (erro instanceof ErroApi && erro.status === 401 && contexto.usuario) {
    contexto.aoSessaoExpirada();
    return;
  }
  const texto = erro instanceof ErroApi ? erro.message : "Algo deu errado. Tente de novo.";
  if (
    formulario &&
    erro instanceof ErroApi &&
    erro.campo &&
    mostrarErroCampo(formulario, erro.campo, texto)
  ) {
    return;
  }
  if (!(erro instanceof ErroApi)) console.error(erro);
  avisar(texto, { erro: true, titulo: tituloDoErro(erro) });
}

function tituloDoErro(erro) {
  if (!(erro instanceof ErroApi)) return "Erro inesperado";
  if (erro.status === 0) return "Sem conexão";
  if (erro.status === 403) return "Sem permissão";
  if (erro.status === 409) return "Não foi possível concluir";
  if (erro.status === 422 || erro.status === 400) return "Verifique os dados";
  return "Erro";
}
