// Usuários e permissões (administrador): quem entra no sistema e com qual perfil.
// Mudar o perfil ou desativar derruba as sessões abertas do usuário na hora.

import { pedir } from "../api.js";
import { contexto, irPara, tratarErro } from "../contexto.js";
import {
  avisar,
  botao,
  campo,
  dataHora,
  dialogo,
  el,
  entrada,
  limparErros,
  militar,
  numero,
  PERFIS,
  selecao,
  selo,
  seloPerfil,
  tabela,
  vazio,
} from "../ui.js";

const DESCRICOES = {
  ADMINISTRADOR: "Acesso completo: cadastros, usuários, permissões, ajustes e baixa.",
  ESTOQUISTA: "Operação do balcão e gestão do estoque (entradas, ajustes, manutenção).",
  EQUIPAMENTISTA: "Operação do balcão: retirada, devolução, posse, estoque e histórico.",
  CONSULTA: "Somente leitura: posse, estoque e histórico.",
};

const opcoesPerfil = (atual) =>
  Object.entries(PERFIS)
    .filter(([valor]) => valor !== "ESTOQUISTA" || atual === "ESTOQUISTA")
    .map(([valor, [texto]]) => ({ valor, texto }));

function senhaCampo(nome = "senha", rotulo = "Senha inicial") {
  return campo({
    rotulo,
    nome,
    ajuda: "De 10 a 128 caracteres. Combine com a pessoa um local seguro para informar.",
    controle: entrada({ nome, tipo: "password", max: 128, auto: "new-password" }),
  });
}

async function novoUsuario() {
  const { militares } = await pedir("GET", "/militares");
  const semUsuario = militares.filter((p) => p.na_unidade && !p.usuario_id);
  if (semUsuario.length === 0) {
    avisar("Todos os militares na unidade já têm usuário. Cadastre o militar primeiro.", {
      erro: true,
    });
    return;
  }
  const perfil = selecao({ nome: "perfil", opcoes: opcoesPerfil(), valor: "EQUIPAMENTISTA" });
  const descricao = el("span", { classe: "campo__ajuda" }, DESCRICOES.EQUIPAMENTISTA);
  perfil.addEventListener("change", () => {
    descricao.textContent = DESCRICOES[perfil.value];
  });
  const blocoPerfil = campo({ rotulo: "Perfil de acesso", nome: "perfil", controle: perfil });
  blocoPerfil.append(descricao);
  dialogo({
    titulo: "Novo usuário",
    subtitulo: "Um usuário por militar. O login é o que ele digita para entrar.",
    corpo: [
      campo({
        rotulo: "Militar",
        nome: "pessoa_id",
        controle: selecao({
          nome: "pessoa_id",
          vazia: "Escolha…",
          opcoes: semUsuario.map((p) => ({
            valor: p.id,
            texto: `${p.posto} ${p.nome_guerra.toUpperCase()} · ${p.nome}`,
          })),
        }),
      }),
      el(
        "div",
        { classe: "grade-campos grade-campos--2" },
        campo({
          rotulo: "Login",
          nome: "login",
          ajuda: "Letras minúsculas, números, ponto e sublinhado",
          controle: entrada({ nome: "login", max: 32, placeholder: "ex.: souza.12", auto: "off" }),
        }),
        blocoPerfil,
      ),
      senhaCampo(),
    ],
    acoes: [
      { texto: "Cancelar" },
      { texto: "Criar usuário", classe: "primario", tipo: "submit", icone: "ok" },
    ],
    aoEnviar: async (form, { fechar }) => {
      limparErros(form);
      const d = Object.fromEntries(new FormData(form));
      try {
        await pedir("POST", "/usuarios", {
          pessoa_id: Number(d.pessoa_id) || null,
          login: d.login,
          perfil: d.perfil,
          senha: d.senha,
        });
        fechar();
        avisar(`Login ${String(d.login).toLowerCase()}`, { titulo: "Usuário criado" });
        irPara("usuarios");
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

function alterarAcesso(u) {
  const proprio = u.id === contexto.usuario.id;
  const perfil = selecao({ nome: "perfil", opcoes: opcoesPerfil(u.perfil), valor: u.perfil });
  const ativo = el("input", { type: "checkbox", name: "ativo", marcado: u.ativo });
  const descricao = el("span", { classe: "campo__ajuda" }, DESCRICOES[u.perfil]);
  perfil.addEventListener("change", () => {
    descricao.textContent = DESCRICOES[perfil.value];
  });
  const blocoPerfil = campo({ rotulo: "Perfil", nome: "perfil", controle: perfil });
  blocoPerfil.append(descricao);
  dialogo({
    titulo: `Acesso de ${u.login}`,
    subtitulo: `${u.posto} ${u.nome_guerra.toUpperCase()} · ${u.nome}`,
    corpo: [
      proprio
        ? el(
            "div",
            { classe: "alerta alerta--info" },
            "Este é o seu usuário: você não pode tirar o próprio acesso de administrador.",
          )
        : null,
      blocoPerfil,
      el("label", { classe: "caixa-marcar" }, ativo, "Usuário ativo (pode entrar no sistema)"),
      el(
        "p",
        { classe: "texto-3 pequeno" },
        "Ao salvar uma mudança, as sessões abertas deste usuário são encerradas.",
      ),
    ],
    acoes: [{ texto: "Cancelar" }, { texto: "Salvar", classe: "primario", tipo: "submit" }],
    aoEnviar: async (form, { fechar }) => {
      try {
        await pedir("PATCH", `/usuarios/${u.id}`, { perfil: perfil.value, ativo: ativo.checked });
        fechar();
        avisar(`${u.login}: ${PERFIS[perfil.value][0]}${ativo.checked ? "" : " (inativo)"}`, {
          titulo: "Acesso atualizado",
        });
        irPara("usuarios");
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

function redefinirSenha(u) {
  dialogo({
    titulo: `Nova senha para ${u.login}`,
    subtitulo: "Use quando o militar esquecer a senha. As sessões dele são encerradas.",
    corpo: senhaCampo("senha", "Nova senha"),
    acoes: [
      { texto: "Cancelar" },
      { texto: "Definir senha", classe: "primario", tipo: "submit", icone: "chave" },
    ],
    aoEnviar: async (form, { fechar }) => {
      limparErros(form);
      try {
        await pedir("POST", `/usuarios/${u.id}/senha`, { senha: new FormData(form).get("senha") });
        fechar();
        avisar(u.login, { titulo: "Senha definida" });
        irPara("usuarios");
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

export async function renderizar(alvo) {
  const { usuarios } = await pedir("GET", "/usuarios");
  const ativos = usuarios.filter((u) => u.ativo);
  const porPerfil = Object.keys(PERFIS).map((p) => [
    p,
    ativos.filter((u) => u.perfil === p).length,
  ]);

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Usuários e permissões"),
        el(
          "p",
          {},
          porPerfil
            .filter(([, n]) => n)
            .map(([p, n]) => `${numero(n)} ${PERFIS[p][0].toLowerCase()}${n > 1 ? "s" : ""}`)
            .join(" · "),
        ),
      ),
      el(
        "div",
        { classe: "cabecalho-pagina__acoes" },
        botao("Novo usuário", {
          classe: "primario",
          iconeNome: "pessoa-mais",
          aoClicar: novoUsuario,
        }),
      ),
    ),
    el(
      "div",
      { classe: "indicadores" },
      Object.entries(DESCRICOES)
        .filter(([p]) => p !== "ESTOQUISTA")
        .map(([p, texto]) =>
          el(
            "div",
            { classe: "indicador" },
            el("div", { classe: "indicador__topo" }, seloPerfil(p)),
            el("div", { classe: "indicador__nota" }, texto),
          ),
        ),
    ),
    el(
      "section",
      { classe: "cartao" },
      usuarios.length === 0
        ? vazio({ icone: "usuarios", titulo: "Nenhum usuário" })
        : tabela({
            linhas: usuarios,
            colunas: [
              {
                titulo: "Usuário",
                principal: true,
                render: (u) =>
                  el(
                    "div",
                    { classe: "celula-principal" },
                    el("strong", { classe: "mono" }, u.login),
                    el("span", {}, u.id === contexto.usuario.id ? "você" : ""),
                  ),
              },
              { titulo: "Militar", render: (u) => militar(u.posto, u.nome_guerra, u.nome) },
              { titulo: "Perfil", classe: "estreita", render: (u) => seloPerfil(u.perfil) },
              {
                titulo: "Situação",
                classe: "estreita",
                render: (u) => (u.ativo ? selo("Ativo", "ok") : selo("Inativo")),
              },
              {
                titulo: "Senha",
                classe: "estreita",
                render: (u) =>
                  u.tem_senha
                    ? el(
                        "span",
                        { classe: "pequeno texto-2" },
                        `definida ${dataHora(u.senha_atualizada_em)}`,
                      )
                    : selo("Sem senha", "atencao"),
              },
              {
                titulo: "Último acesso",
                classe: "estreita",
                render: (u) =>
                  u.ultima_entrada
                    ? dataHora(u.ultima_entrada)
                    : el("span", { classe: "texto-3" }, "—"),
              },
              {
                titulo: "",
                rotulo: "",
                classe: "direita estreita",
                render: (u) =>
                  el(
                    "div",
                    { classe: "linha-acoes" },
                    botao("Acesso", {
                      classe: "fantasma pequeno",
                      iconeNome: "usuarios",
                      aoClicar: () => alterarAcesso(u),
                    }),
                    botao("Senha", {
                      classe: "fantasma pequeno",
                      iconeNome: "chave",
                      aoClicar: () => redefinirSenha(u),
                    }),
                  ),
              },
            ],
          }),
    ),
  );
}
