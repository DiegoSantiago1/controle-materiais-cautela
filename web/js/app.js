// Tela do equipamentista: cautelas em aberto, nova retirada e devolução.
//
// Regra de segurança desta página: NENHUM dado vira HTML. Todo elemento é criado com
// createElement e todo texto entra por textContent (função el abaixo). Um nome de
// material ou uma observação com "<script>" aparece como texto, nunca executa. A CSP
// do servidor (sem script inline) é a segunda camada.

import { ErroApi, pedir } from "./api.js";

// ---------------------------------------------------------------- utilidades
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...filhos) {
  const elemento = document.createElement(tag);
  for (const [chave, valor] of Object.entries(props)) {
    if (valor === undefined || valor === null || valor === false) continue;
    if (chave === "classe") elemento.className = valor;
    else if (chave.startsWith("on")) elemento.addEventListener(chave.slice(2), valor);
    else elemento.setAttribute(chave, valor === true ? "" : String(valor));
  }
  for (const filho of filhos.flat()) {
    if (filho === undefined || filho === null || filho === false) continue;
    elemento.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  return elemento;
}

const formatoDataHora = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Recife",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
const dataHora = (iso) => formatoDataHora.format(new Date(iso));

function duracao(ms) {
  const minutos = Math.round(Math.abs(ms) / 60_000);
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 48) return `${horas} h`;
  return `${Math.round(horas / 24)} dias`;
}

const DUAS_HORAS = 2 * 60 * 60 * 1000;

/** Situação de uma cautela pelo prazo: sempre com texto, a cor só reforça. */
function situacao(prazoIso) {
  const falta = new Date(prazoIso).getTime() - Date.now();
  if (falta < 0) return { tipo: "vencida", texto: `Vencida há ${duracao(falta)}` };
  if (falta < DUAS_HORAS) return { tipo: "atencao", texto: `Vence em ${duracao(falta)}` };
  return { tipo: "ok", texto: `No prazo · ${duracao(falta)}` };
}

const NOMES_DE_STATUS = {
  DISPONIVEL: "Disponível",
  CAUTELADA: "Cautelada",
  EM_MANUTENCAO: "Em manutenção",
  NAO_LOCALIZADA: "Não localizada",
  BAIXA_PENDENTE: "Baixa pendente",
  BAIXADA: "Baixada",
  AGUARDANDO_TOMBAMENTO: "Sem tombamento",
};

function avisar(texto, erro = false) {
  const aviso = el(
    "div",
    { classe: `aviso-flutuante${erro ? " aviso-flutuante--erro" : ""}` },
    texto,
  );
  $("avisos").append(aviso);
  setTimeout(() => aviso.remove(), erro ? 6000 : 4000);
}

function mostrarErro(elemento, texto) {
  elemento.textContent = texto;
  elemento.hidden = !texto;
}

/** Sessão vencida em qualquer pedido: volta para a tela de entrada. */
function tratarErro(erro, alvo) {
  if (erro instanceof ErroApi && erro.status === 401 && estado.usuario) {
    mostrarEntrar("Sua sessão terminou. Entre de novo.");
    return;
  }
  const texto = erro instanceof ErroApi ? erro.message : "Algo deu errado. Tente de novo.";
  if (alvo) mostrarErro(alvo, texto);
  else avisar(texto, true);
}

function aoParar(funcao, ms = 250) {
  let espera;
  return (...args) => {
    clearTimeout(espera);
    espera = setTimeout(() => funcao(...args), ms);
  };
}

// ---------------------------------------------------------------- estado
const estado = {
  usuario: null,
  cautelas: [],
  unidade: null,
  pessoa: null,
  emDevolucao: null,
};

const podeMovimentar = () => estado.usuario && estado.usuario.perfil !== "CONSULTA";

// ---------------------------------------------------------------- entrar e sair
function mostrarEntrar(mensagem = "") {
  estado.usuario = null;
  $("tela-app").hidden = true;
  $("tela-entrar").hidden = false;
  $("entrar-senha").value = "";
  mostrarErro($("entrar-erro"), mensagem);
  $("entrar-login").focus();
}

function mostrarApp(usuario) {
  estado.usuario = usuario;
  $("tela-entrar").hidden = true;
  $("tela-app").hidden = false;
  $("usuario-nome").textContent = usuario.nome;
  $("usuario-perfil").textContent = usuario.perfil.toLowerCase();
  $("aviso-consulta").hidden = podeMovimentar();
  $("aviso-consulta-retirada").hidden = podeMovimentar();
  $("botao-retirar").hidden = !podeMovimentar();
  trocarAba("abertas");
  carregarCautelas();
}

$("form-entrar").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const login = $("entrar-login").value.trim();
  const senha = $("entrar-senha").value;
  if (!login || !senha) {
    mostrarErro($("entrar-erro"), "Informe login e senha.");
    return;
  }
  const botao = evento.submitter;
  botao.disabled = true;
  try {
    const { usuario } = await pedir("POST", "/sessao", { login, senha });
    mostrarErro($("entrar-erro"), "");
    mostrarApp(usuario);
  } catch (erro) {
    $("entrar-senha").value = "";
    tratarErro(erro, $("entrar-erro"));
  } finally {
    botao.disabled = false;
  }
});

$("botao-sair").addEventListener("click", async () => {
  try {
    await pedir("DELETE", "/sessao");
  } finally {
    limparRetirada();
    mostrarEntrar();
  }
});

// ---------------------------------------------------------------- abas
function trocarAba(nome) {
  for (const botao of document.querySelectorAll(".abas__aba")) {
    if (botao.dataset.aba === nome) botao.setAttribute("aria-current", "page");
    else botao.removeAttribute("aria-current");
  }
  $("aba-abertas").hidden = nome !== "abertas";
  $("aba-retirada").hidden = nome !== "retirada";
}

for (const botao of document.querySelectorAll(".abas__aba")) {
  botao.addEventListener("click", () => {
    trocarAba(botao.dataset.aba);
    if (botao.dataset.aba === "abertas") carregarCautelas();
    else if (!estado.unidade) $("busca-material").focus();
  });
}

// ---------------------------------------------------------------- cautelas em aberto
async function carregarCautelas() {
  try {
    const { cautelas } = await pedir("GET", "/cautelas");
    estado.cautelas = cautelas;
    desenharCautelas();
  } catch (erro) {
    tratarErro(erro);
  }
}

function desenharCautelas() {
  const vencidas = estado.cautelas.filter((c) => new Date(c.prazo).getTime() < Date.now()).length;
  $("contador-abertas").textContent = String(estado.cautelas.length);
  $("resumo-abertas").replaceChildren(
    el(
      "div",
      { classe: "indicador" },
      el("span", { classe: "indicador__valor" }, estado.cautelas.length),
      el("span", { classe: "indicador__rotulo" }, "em aberto"),
    ),
    el(
      "div",
      { classe: `indicador${vencidas > 0 ? " indicador--vencida" : ""}` },
      el("span", { classe: "indicador__valor" }, vencidas),
      el("span", { classe: "indicador__rotulo" }, vencidas === 1 ? "vencida" : "vencidas"),
    ),
  );

  const filtro = normalizar($("filtro-abertas").value);
  const visiveis = estado.cautelas.filter(
    (c) =>
      !filtro ||
      normalizar(
        [c.material, c.bmp, c.numero_serie, c.pessoa, c.matricula, c.setor].join(" "),
      ).includes(filtro),
  );

  const lista = $("lista-abertas");
  if (visiveis.length === 0) {
    lista.replaceChildren(
      el(
        "li",
        { classe: "vazio" },
        estado.cautelas.length === 0
          ? "Nenhuma cautela em aberto."
          : "Nada encontrado com esse filtro.",
      ),
    );
    return;
  }
  lista.replaceChildren(...visiveis.map(cartaoDaCautela));
}

function cartaoDaCautela(c) {
  const s = situacao(c.prazo);
  return el(
    "li",
    { classe: `cartao cautela cautela--${s.tipo}` },
    el(
      "div",
      { classe: "cautela__linha" },
      el("h3", { classe: "cautela__material" }, c.material),
      el("span", { classe: `selo selo--${s.tipo}` }, s.texto),
    ),
    el(
      "p",
      { classe: "cautela__detalhe" },
      c.bmp ? el("span", { classe: "bmp" }, `BMP ${c.bmp}`) : "Sem BMP",
      c.numero_serie ? ` · série ${c.numero_serie}` : "",
    ),
    el("p", { classe: "cautela__detalhe" }, `Com ${c.pessoa} (${c.setor}) · mat. ${c.matricula}`),
    el(
      "p",
      { classe: "cautela__datas" },
      `Retirada ${dataHora(c.retirada_em)} · prazo ${dataHora(c.prazo)}`,
    ),
    podeMovimentar() &&
      el(
        "button",
        {
          classe: "botao botao--secundario botao--pequeno",
          type: "button",
          onclick: () => abrirDevolucao(c),
        },
        "Receber devolução",
      ),
  );
}

function normalizar(texto) {
  return (texto ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

$("filtro-abertas").addEventListener("input", desenharCautelas);

// ---------------------------------------------------------------- devolução
function abrirDevolucao(cautela) {
  estado.emDevolucao = cautela;
  $("devolucao-resumo").textContent =
    `${cautela.material}${cautela.bmp ? ` (BMP ${cautela.bmp})` : ""}, com ${cautela.pessoa}.`;
  $("form-devolucao").reset();
  atualizarRegraDaObservacao();
  mostrarErro($("devolucao-erro"), "");
  $("dialogo-devolucao").showModal();
}

function estadoEscolhido() {
  return $("form-devolucao").querySelector("input[name=estado]:checked").value;
}

function atualizarRegraDaObservacao() {
  const obrigatoria = estadoEscolhido() !== "BOM";
  $("observacao-regra").textContent = obrigatoria
    ? "(obrigatória: descreva o problema)"
    : "(opcional)";
  $("devolucao-observacao").required = obrigatoria;
}

for (const radio of document.querySelectorAll("input[name=estado]")) {
  radio.addEventListener("change", atualizarRegraDaObservacao);
}

$("devolucao-cancelar").addEventListener("click", () => $("dialogo-devolucao").close());

$("form-devolucao").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const cautela = estado.emDevolucao;
  const estadoMaterial = estadoEscolhido();
  const observacao = $("devolucao-observacao").value.trim();
  if (estadoMaterial !== "BOM" && !observacao) {
    mostrarErro($("devolucao-erro"), "Descreva o problema do material na observação.");
    $("devolucao-observacao").focus();
    return;
  }
  const botao = $("devolucao-confirmar");
  botao.disabled = true;
  try {
    await pedir("POST", "/devolucoes", {
      unidade_id: cautela.unidade_id,
      pessoa_id: cautela.pessoa_id,
      estado: estadoMaterial,
      observacao: observacao || null,
    });
    $("dialogo-devolucao").close();
    avisar(`Devolução registrada: ${cautela.material}.`);
    carregarCautelas();
  } catch (erro) {
    tratarErro(erro, $("devolucao-erro"));
    // A cautela mudou enquanto a tela estava aberta: atualiza a lista por trás.
    if (erro instanceof ErroApi && erro.status === 409) carregarCautelas();
  } finally {
    botao.disabled = false;
  }
});

// ---------------------------------------------------------------- nova retirada
// Buscas com "senha": se o usuário digitar rápido, só a resposta da última busca vale.
function criarBusca({ entrada, lista, caminho, chave, desenhar }) {
  let ultima = 0;
  const buscar = aoParar(async () => {
    const termo = entrada.value.trim();
    const minha = ++ultima;
    if (termo.length < 2) {
      lista.replaceChildren();
      return;
    }
    try {
      const dados = await pedir("GET", `${caminho}?busca=${encodeURIComponent(termo)}`);
      if (minha !== ultima) return;
      const itens = dados[chave];
      lista.replaceChildren(
        ...(itens.length === 0
          ? [el("li", { classe: "resultados__nota" }, "Nada encontrado.")]
          : itens.map(desenhar)),
      );
    } catch (erro) {
      if (minha === ultima) tratarErro(erro);
    }
  });
  entrada.addEventListener("input", buscar);
}

function resultado({ titulo, sub, selo, desabilitado, aoEscolher }) {
  return el(
    "li",
    {},
    el(
      "button",
      { classe: "resultado", type: "button", disabled: desabilitado, onclick: aoEscolher },
      el(
        "span",
        { classe: "resultado__texto" },
        el("span", { classe: "resultado__titulo" }, titulo),
        el("span", { classe: "resultado__sub" }, sub),
      ),
      selo,
    ),
  );
}

criarBusca({
  entrada: $("busca-material"),
  lista: $("resultados-material"),
  caminho: "/unidades",
  chave: "unidades",
  desenhar: (u) => {
    const livre = u.status === "DISPONIVEL";
    const rotulo =
      u.status === "CAUTELADA" && u.detentor
        ? `Com ${u.detentor}`
        : (NOMES_DE_STATUS[u.status] ?? u.status);
    return resultado({
      titulo: u.material,
      sub: [u.bmp ? `BMP ${u.bmp}` : "sem BMP", u.numero_serie && `série ${u.numero_serie}`]
        .filter(Boolean)
        .join(" · "),
      selo: el("span", { classe: `selo ${livre ? "selo--ok" : "selo--neutro"}` }, rotulo),
      desabilitado: !livre,
      aoEscolher: () => escolherUnidade(u),
    });
  },
});

criarBusca({
  entrada: $("busca-pessoa"),
  lista: $("resultados-pessoa"),
  caminho: "/pessoas",
  chave: "pessoas",
  desenhar: (p) =>
    resultado({
      titulo: p.nome,
      sub: `${p.setor} · mat. ${p.matricula}`,
      selo: null,
      desabilitado: false,
      aoEscolher: () => escolherPessoa(p),
    }),
});

function mostrarEscolhido(prefixo, titulo, sub, aoTrocar) {
  const caixa = $(`escolhido-${prefixo}`);
  caixa.replaceChildren(
    el(
      "span",
      { classe: "escolhido__texto" },
      titulo,
      el("span", { classe: "escolhido__sub" }, sub),
    ),
    el(
      "button",
      { classe: "botao botao--fantasma botao--pequeno", type: "button", onclick: aoTrocar },
      "Trocar",
    ),
  );
  caixa.hidden = false;
  $(`busca-${prefixo}`).closest(".campo").hidden = true;
  $(`resultados-${prefixo}`).replaceChildren();
  $(`passo-${prefixo}`).classList.add("passo--feito");
}

function reabrirBusca(prefixo) {
  $(`escolhido-${prefixo}`).hidden = true;
  $(`busca-${prefixo}`).closest(".campo").hidden = false;
  $(`passo-${prefixo}`).classList.remove("passo--feito");
  $(`busca-${prefixo}`).focus();
}

function escolherUnidade(unidade) {
  estado.unidade = unidade;
  mostrarEscolhido(
    "material",
    unidade.material,
    `${unidade.bmp ? `BMP ${unidade.bmp}` : "sem BMP"} · prazo de ${duracao(unidade.prazo_devolucao_horas * 3_600_000)}`,
    () => {
      estado.unidade = null;
      reabrirBusca("material");
      atualizarBotaoRetirar();
    },
  );
  atualizarBotaoRetirar();
  if (!estado.pessoa) $("busca-pessoa").focus();
}

function escolherPessoa(pessoa) {
  estado.pessoa = pessoa;
  mostrarEscolhido("pessoa", pessoa.nome, `${pessoa.setor} · mat. ${pessoa.matricula}`, () => {
    estado.pessoa = null;
    reabrirBusca("pessoa");
    atualizarBotaoRetirar();
  });
  atualizarBotaoRetirar();
  $("retirada-finalidade").focus();
}

function atualizarBotaoRetirar() {
  const pronto = Boolean(estado.unidade && estado.pessoa && podeMovimentar());
  $("botao-retirar").disabled = !pronto;
  $("passo-confirmar").classList.toggle("passo--feito", pronto);
}

function limparRetirada() {
  estado.unidade = null;
  estado.pessoa = null;
  $("form-retirada").reset();
  for (const prefixo of ["material", "pessoa"]) {
    $(`escolhido-${prefixo}`).hidden = true;
    $(`busca-${prefixo}`).closest(".campo").hidden = false;
    $(`resultados-${prefixo}`).replaceChildren();
    $(`passo-${prefixo}`).classList.remove("passo--feito");
  }
  mostrarErro($("retirada-erro"), "");
  atualizarBotaoRetirar();
}

$("form-retirada").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (!estado.unidade || !estado.pessoa) return;
  const botao = $("botao-retirar");
  botao.disabled = true;
  try {
    const { prazo } = await pedir("POST", "/retiradas", {
      unidade_id: estado.unidade.id,
      pessoa_id: estado.pessoa.id,
      finalidade: $("retirada-finalidade").value.trim() || null,
    });
    avisar(
      `Retirada registrada: ${estado.unidade.material} com ${estado.pessoa.nome}. Devolver até ${dataHora(prazo)}.`,
    );
    limparRetirada();
    trocarAba("abertas");
    carregarCautelas();
  } catch (erro) {
    tratarErro(erro, $("retirada-erro"));
    atualizarBotaoRetirar();
  }
});

// ---------------------------------------------------------------- início
async function iniciar() {
  try {
    const { usuario } = await pedir("GET", "/sessao");
    if (usuario) mostrarApp(usuario);
    else mostrarEntrar();
  } catch (erro) {
    mostrarEntrar(erro instanceof ErroApi && erro.status === 0 ? erro.message : "");
  }
}

// A situação (vencida, vence logo) depende do relógio: redesenha a cada minuto.
setInterval(() => {
  if (estado.usuario && !$("aba-abertas").hidden) desenharCautelas();
}, 60_000);

iniciar();
