// Minha conta: dados de quem está logado e troca da própria senha (exige a atual).

import { pedir } from "../api.js";
import { contexto, tratarErro } from "../contexto.js";
import {
  avisar,
  botao,
  campo,
  cartao,
  comCarregamento,
  el,
  entrada,
  limparErros,
  militar,
  mostrarErroCampo,
  seloPerfil,
} from "../ui.js";

export async function renderizar(alvo) {
  const u = contexto.usuario;
  const formulario = el(
    "form",
    { novalidate: true, classe: "passos" },
    campo({
      rotulo: "Senha atual",
      nome: "senha_atual",
      controle: entrada({
        nome: "senha_atual",
        tipo: "password",
        max: 128,
        auto: "current-password",
      }),
    }),
    campo({
      rotulo: "Senha nova",
      nome: "senha_nova",
      ajuda:
        "De 10 a 128 caracteres. Uma frase longa é mais segura que uma senha curta cheia de símbolos.",
      controle: entrada({ nome: "senha_nova", tipo: "password", max: 128, auto: "new-password" }),
    }),
    campo({
      rotulo: "Repita a senha nova",
      nome: "confirmacao",
      controle: entrada({ nome: "confirmacao", tipo: "password", max: 128, auto: "new-password" }),
    }),
  );
  const salvar = botao("Trocar senha", { classe: "primario", tipo: "submit", iconeNome: "chave" });
  formulario.append(el("div", {}, salvar));
  formulario.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    limparErros(formulario);
    const d = Object.fromEntries(new FormData(formulario));
    if (d.senha_nova !== d.confirmacao) {
      mostrarErroCampo(formulario, "confirmacao", "As duas senhas novas não são iguais.");
      return;
    }
    await comCarregamento(salvar, async () => {
      try {
        await pedir("POST", "/sessao/senha", {
          senha_atual: d.senha_atual,
          senha_nova: d.senha_nova,
        });
        formulario.reset();
        avisar("As outras sessões abertas com o seu login foram encerradas.", {
          titulo: "Senha trocada",
        });
      } catch (erro) {
        tratarErro(erro, formulario);
      }
    });
  });

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el("div", { classe: "cabecalho-pagina__texto" }, el("h2", {}, "Minha conta")),
    ),
    el(
      "div",
      { classe: "duas-colunas" },
      cartao({
        titulo: "Identificação",
        corpo: el(
          "dl",
          { classe: "detalhes" },
          el("dt", {}, "Militar"),
          el("dd", {}, militar(u.posto, u.nome_guerra, u.nome)),
          el("dt", {}, "Login"),
          el("dd", { classe: "mono" }, u.login),
          el("dt", {}, "Perfil"),
          el("dd", {}, seloPerfil(u.perfil)),
        ),
      }),
      cartao({
        titulo: "Trocar senha",
        sub: "Você continua conectado neste aparelho.",
        corpo: formulario,
      }),
    ),
  );
}
