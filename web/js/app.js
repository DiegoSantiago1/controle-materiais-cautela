// Casca da aplicação: entrar e sair, menu por perfil, roteador por hash (#/estoque) e tema.
// Cada página é um módulo em js/paginas/, carregado só quando aberto.

import { ErroApi, pedir } from "./api.js";
import {
  ADMINISTRACAO,
  contexto,
  OPERACIONAIS,
  pode,
  referencias,
  tratarErro,
} from "./contexto.js";
import { $, el, esqueleto, fecharPainel, icone, PERFIS, rotuloMilitar, vazio } from "./ui.js";

const TODOS = ["ADMINISTRADOR", "ESTOQUISTA", "EQUIPAMENTISTA", "CONSULTA"];

const ROTAS = {
  inicio: { titulo: "Início", grupo: "Operação", icone: "inicio", perfis: TODOS },
  retirada: { titulo: "Nova retirada", grupo: "Operação", icone: "retirada", perfis: OPERACIONAIS },
  devolucao: {
    titulo: "Receber devolução",
    grupo: "Operação",
    icone: "devolucao",
    perfis: OPERACIONAIS,
  },
  posse: { titulo: "Em posse", grupo: "Operação", icone: "posse", perfis: TODOS },
  estoque: { titulo: "Estoque", grupo: "Controle", icone: "estoque", perfis: TODOS },
  historico: { titulo: "Histórico", grupo: "Controle", icone: "historico", perfis: TODOS },
  materiais: {
    titulo: "Materiais e categorias",
    grupo: "Administração",
    icone: "materiais",
    perfis: ADMINISTRACAO,
  },
  militares: {
    titulo: "Militares",
    grupo: "Administração",
    icone: "militares",
    perfis: ADMINISTRACAO,
  },
  usuarios: {
    titulo: "Usuários e permissões",
    grupo: "Administração",
    icone: "usuarios",
    perfis: ADMINISTRACAO,
  },
  auditoria: {
    titulo: "Auditoria",
    grupo: "Administração",
    icone: "auditoria",
    perfis: ADMINISTRACAO,
  },
  conta: { titulo: "Minha conta", grupo: "Conta", icone: "conta", perfis: TODOS },
};

const PAGINAS = {
  inicio: () => import("./paginas/inicio.js"),
  retirada: () => import("./paginas/retirada.js"),
  devolucao: () => import("./paginas/devolucao.js"),
  posse: () => import("./paginas/posse.js"),
  estoque: () => import("./paginas/estoque.js"),
  historico: () => import("./paginas/historico.js"),
  materiais: () => import("./paginas/materiais.js"),
  militares: () => import("./paginas/militares.js"),
  usuarios: () => import("./paginas/usuarios.js"),
  auditoria: () => import("./paginas/auditoria.js"),
  conta: () => import("./paginas/conta.js"),
};

let limpezaDaPagina = null;
let contagens = { vencidas: 0, abaixo_do_minimo: 0, em_posse: 0 };

// ------------------------------------------------------------ tema
const CHAVE_TEMA = "almox-tema";

function temaSalvo() {
  try {
    return localStorage.getItem(CHAVE_TEMA);
  } catch {
    return null;
  }
}

function aplicarTema(tema) {
  if (tema === "claro" || tema === "escuro") document.documentElement.dataset.tema = tema;
  else delete document.documentElement.dataset.tema;
  const escuro = temaEfetivo() === "escuro";
  $("botao-tema").replaceChildren(
    icone(escuro ? "sol" : "lua", "icone--16"),
    el("span", {}, escuro ? "Claro" : "Escuro"),
  );
}

function temaEfetivo() {
  const definido = document.documentElement.dataset.tema;
  if (definido) return definido;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro";
}

$("botao-tema").addEventListener("click", () => {
  const novo = temaEfetivo() === "escuro" ? "claro" : "escuro";
  try {
    localStorage.setItem(CHAVE_TEMA, novo);
  } catch {
    // sem armazenamento (janela privada): vale só nesta visita
  }
  aplicarTema(novo);
});

// ------------------------------------------------------------ entrar e sair
function mostrarEntrar(mensagem = "") {
  contexto.usuario = null;
  contexto.referencias = null;
  fecharPainel();
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  $("tela-app").hidden = true;
  $("tela-entrar").hidden = false;
  $("entrar-senha").value = "";
  const erro = $("entrar-erro");
  erro.replaceChildren(...(mensagem ? [icone("info"), el("span", {}, mensagem)] : []));
  erro.className = mensagem.startsWith("Sua sessão") ? "alerta alerta--info" : "alerta";
  erro.hidden = !mensagem;
  document.title = "Entrar · Controle de Materiais e Cautela";
  $("entrar-login").focus();
}
contexto.aoSessaoExpirada = () => mostrarEntrar("Sua sessão terminou. Entre de novo.");

async function mostrarApp(usuario) {
  contexto.usuario = usuario;
  $("tela-entrar").hidden = true;
  $("tela-app").hidden = false;
  $("usuario-nome").textContent = rotuloMilitar(usuario.posto, usuario.nome_guerra);
  $("usuario-perfil").textContent = PERFIS[usuario.perfil]?.[0] ?? usuario.perfil;
  $("usuario-avatar").textContent = String(usuario.nome_guerra ?? usuario.login)
    .slice(0, 2)
    .toUpperCase();
  montarMenu();
  try {
    await referencias(true);
  } catch (erro) {
    tratarErro(erro);
  }
  atualizarContagens();
  if (!location.hash || location.hash === "#") location.hash = "#/inicio";
  else navegar();
}

$("form-entrar").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const login = $("entrar-login").value.trim();
  const senha = $("entrar-senha").value;
  const erro = $("entrar-erro");
  if (!login || !senha) {
    erro.className = "alerta";
    erro.replaceChildren(icone("alerta"), el("span", {}, "Informe login e senha."));
    erro.hidden = false;
    return;
  }
  const botaoEntrar = evento.submitter ?? $("form-entrar").querySelector("button");
  botaoEntrar.disabled = true;
  botaoEntrar.textContent = "Entrando…";
  try {
    const { usuario } = await pedir("POST", "/sessao", { login, senha });
    erro.hidden = true;
    await mostrarApp(usuario);
  } catch (falha) {
    $("entrar-senha").value = "";
    erro.className = "alerta";
    erro.replaceChildren(
      icone("alerta"),
      el("span", {}, falha instanceof ErroApi ? falha.message : "Algo deu errado. Tente de novo."),
    );
    erro.hidden = false;
  } finally {
    botaoEntrar.disabled = false;
    botaoEntrar.textContent = "Entrar";
  }
});

$("botao-sair").addEventListener("click", async () => {
  try {
    await pedir("DELETE", "/sessao");
  } finally {
    history.replaceState(null, "", location.pathname);
    mostrarEntrar();
  }
});

// ------------------------------------------------------------ menu
function link(rota, { barra = false } = {}) {
  const def = ROTAS[rota];
  if (barra) {
    const destaque = rota === "retirada";
    return el(
      "a",
      {
        classe: `barra__item${destaque ? " barra__item--destaque" : ""}`,
        href: `#/${rota}`,
        "data-rota": rota,
      },
      el("span", { classe: "barra__bolha" }, icone(def.icone)),
      { retirada: "Retirar", devolucao: "Devolver", posse: "Em posse" }[rota] ?? def.titulo,
    );
  }
  return el(
    "a",
    { classe: "nav__link", href: `#/${rota}`, "data-rota": rota },
    icone(def.icone),
    el("span", {}, def.titulo),
    rota === "posse"
      ? el("span", {
          classe: "nav__contagem nav__contagem--alerta",
          id: "contagem-vencidas",
          hidden: true,
        })
      : null,
    rota === "estoque"
      ? el("span", { classe: "nav__contagem", id: "contagem-estoque", hidden: true })
      : null,
  );
}

function montarMenu() {
  const grupos = new Map();
  for (const [rota, def] of Object.entries(ROTAS)) {
    if (!pode(def.perfis)) continue;
    if (!grupos.has(def.grupo)) grupos.set(def.grupo, []);
    grupos.get(def.grupo).push(rota);
  }
  $("nav-links").replaceChildren(
    ...[...grupos].map(([grupo, rotas]) =>
      el(
        "div",
        { classe: "nav__grupo" },
        el("div", { classe: "nav__titulo" }, grupo),
        rotas.map((r) => link(r)),
      ),
    ),
  );
  const atalhos = pode(OPERACIONAIS)
    ? ["inicio", "retirada", "devolucao", "posse"]
    : ["inicio", "posse", "estoque", "historico"];
  $("barra").replaceChildren(
    ...atalhos.map((r) => link(r, { barra: true })),
    el(
      "button",
      { classe: "barra__item", type: "button", onclick: abrirMenu, "aria-controls": "nav" },
      el("span", { classe: "barra__bolha" }, icone("menu")),
      "Menu",
    ),
  );
}

function marcarMenu(rota) {
  for (const a of document.querySelectorAll("[data-rota]")) {
    if (a.dataset.rota === rota) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

/** Contadores do menu (vencidas, estoque abaixo do mínimo). Chamado depois de cada operação. */
export async function atualizarContagens() {
  try {
    const { contadores } = await pedir("GET", "/resumo");
    contagens = contadores;
    const vencidas = $("contagem-vencidas");
    if (vencidas) {
      // Mostra "N vencidas", e não só o número: ao lado de "Em posse", um número solto
      // parece o total em posse (que é outro, o do card do início).
      vencidas.textContent = `${contadores.vencidas} vencida${contadores.vencidas === 1 ? "" : "s"}`;
      vencidas.hidden = contadores.vencidas === 0;
      vencidas.title = `${contadores.vencidas} posse(s) vencida(s)`;
    }
    const estoque = $("contagem-estoque");
    if (estoque) {
      estoque.textContent = String(contadores.abaixo_do_minimo);
      estoque.hidden = contadores.abaixo_do_minimo === 0;
      estoque.title = `${contadores.abaixo_do_minimo} material(is) abaixo do mínimo`;
    }
  } catch {
    // contadores são acessórios: a página continua funcionando sem eles
  }
}
window.addEventListener("almox:mudou", atualizarContagens);

function abrirMenu() {
  $("nav").classList.add("nav--aberta");
  $("veu").hidden = false;
  $("nav-abrir").setAttribute("aria-expanded", "true");
  $("nav").querySelector(".nav__link")?.focus();
}

function fecharMenu() {
  $("nav").classList.remove("nav--aberta");
  $("veu").hidden = true;
  $("nav-abrir").setAttribute("aria-expanded", "false");
}

$("nav-abrir").addEventListener("click", abrirMenu);
$("nav-fechar").addEventListener("click", fecharMenu);
$("veu").addEventListener("click", fecharMenu);
document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && $("nav").classList.contains("nav--aberta")) fecharMenu();
});

// ------------------------------------------------------------ roteador
function lerHash() {
  const [caminho, busca = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return { rota: caminho || "inicio", parametros: Object.fromEntries(new URLSearchParams(busca)) };
}

async function navegar() {
  if (!contexto.usuario) return;
  fecharMenu();
  fecharPainel();
  limpezaDaPagina?.();
  limpezaDaPagina = null;

  let { rota, parametros } = lerHash();
  if (!ROTAS[rota]) rota = "inicio";
  const def = ROTAS[rota];
  marcarMenu(rota);
  $("topo-titulo").textContent = def.titulo;
  $("topo-trilha").textContent = def.grupo;
  document.title = `${def.titulo} · Controle de Materiais e Cautela`;

  const conteudo = $("conteudo");
  if (!pode(def.perfis)) {
    conteudo.replaceChildren(
      vazio({
        icone: "chave",
        titulo: "Sem acesso a esta página",
        texto: "Seu perfil não tem permissão para esta função. Fale com o administrador.",
      }),
    );
    return;
  }
  conteudo.replaceChildren(el("section", { classe: "cartao" }, esqueleto(8)));
  try {
    const modulo = await PAGINAS[rota]();
    if (lerHash().rota !== rota && ROTAS[lerHash().rota]) return; // o usuário já foi para outra
    const limpeza = await modulo.renderizar(conteudo, parametros, { contagens });
    limpezaDaPagina = typeof limpeza === "function" ? limpeza : null;
  } catch (erro) {
    tratarErro(erro);
    if (contexto.usuario) {
      conteudo.replaceChildren(
        vazio({
          icone: "alerta",
          titulo: "Não foi possível carregar a página",
          texto: "Tente atualizar.",
        }),
      );
    }
  }
  conteudo.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

window.addEventListener("hashchange", navegar);
$("botao-atualizar").addEventListener("click", () => {
  atualizarContagens();
  navegar();
});

// ------------------------------------------------------------ relógio do topo
const formatoRelogio = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Recife",
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
function relogio() {
  $("topo-relogio").textContent = formatoRelogio.format(new Date()).replace(",", " ·");
}
relogio();
setInterval(relogio, 30_000);
setInterval(() => {
  if (contexto.usuario) atualizarContagens();
}, 60_000);

// ------------------------------------------------------------ início
async function iniciar() {
  aplicarTema(temaSalvo());
  try {
    const { usuario } = await pedir("GET", "/sessao");
    if (usuario) await mostrarApp(usuario);
    else mostrarEntrar();
  } catch (erro) {
    mostrarEntrar(erro instanceof ErroApi && erro.status === 0 ? erro.message : "");
  }
}

iniciar();
