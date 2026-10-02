// Peças de interface usadas por todas as páginas.
//
// Regra de segurança: NENHUM dado vira HTML. Todo elemento é criado com createElement e
// todo texto entra por textContent (função el). Um nome de material ou uma observação com
// "<script>" aparece como texto, nunca executa. A CSP do servidor (sem script inline) é a
// segunda camada.

export const $ = (id) => document.getElementById(id);

const SVG = "http://www.w3.org/2000/svg";

export function el(tag, props = {}, ...filhos) {
  const elemento = document.createElement(tag);
  for (const [chave, valor] of Object.entries(props)) {
    if (valor === undefined || valor === null || valor === false) continue;
    if (chave === "classe") elemento.className = valor;
    else if (chave === "texto") elemento.textContent = valor;
    else if (chave.startsWith("on") && typeof valor === "function") {
      elemento.addEventListener(chave.slice(2), valor);
    } else if (chave === "valor") elemento.value = valor;
    else if (chave === "marcado") elemento.checked = Boolean(valor);
    else elemento.setAttribute(chave, valor === true ? "" : String(valor));
  }
  for (const filho of filhos.flat(Infinity)) {
    if (filho === undefined || filho === null || filho === false) continue;
    elemento.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  return elemento;
}

/** Ícone do "sprite" do index.html: <svg><use href="#i-nome"></svg>. */
export function icone(nome, classe = "") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", `icone ${classe}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const uso = document.createElementNS(SVG, "use");
  uso.setAttribute("href", `#i-${nome}`);
  svg.append(uso);
  return svg;
}

// ------------------------------------------------------------ formatação
const FUSO = "America/Recife";
const fDataHora = new Intl.DateTimeFormat("pt-BR", {
  timeZone: FUSO,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const fDataHoraCurta = new Intl.DateTimeFormat("pt-BR", {
  timeZone: FUSO,
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
const fNumero = new Intl.NumberFormat("pt-BR");
const fDinheiro = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export const dataHora = (iso) => (iso ? fDataHora.format(new Date(iso)).replace(",", "") : "—");
export const dataHoraCurta = (iso) =>
  iso ? fDataHoraCurta.format(new Date(iso)).replace(",", "") : "—";
/** Data sem hora (coluna date do banco chega como "AAAA-MM-DD" ou ISO à meia-noite UTC). */
export function data(valor) {
  if (!valor) return "—";
  const [a, m, d] = String(valor).slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}
export const numero = (n) => fNumero.format(n ?? 0);
export const dinheiro = (n) => fDinheiro.format(n ?? 0);
export const hojeIso = () => new Date().toLocaleDateString("sv-SE", { timeZone: FUSO });

export function duracao(ms) {
  const minutos = Math.round(Math.abs(ms) / 60_000);
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 48) return `${horas} h`;
  return `${Math.round(horas / 24)} dias`;
}

export function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

export function aoParar(funcao, ms = 250) {
  let espera;
  return (...args) => {
    clearTimeout(espera);
    espera = setTimeout(() => funcao(...args), ms);
  };
}

// ------------------------------------------------------------ militar e selos
const OFICIAIS = new Set(["TEN", "CAP", "MAJ", "TEN-CEL", "CEL"]);
const GRADUADOS = new Set(["SGT", "ST"]);

export function seloPosto(posto) {
  const classe = OFICIAIS.has(posto)
    ? "posto posto--oficial"
    : GRADUADOS.has(posto)
      ? "posto posto--graduado"
      : "posto";
  return el("span", { classe, title: posto }, posto ?? "—");
}

/** "SGT SOUZA": posto + nome de guerra, como o militar é chamado no balcão. */
export const rotuloMilitar = (posto, guerra) =>
  [posto, String(guerra ?? "").toUpperCase()].filter(Boolean).join(" ");

export function militar(posto, guerra, sub) {
  return el(
    "span",
    { classe: "militar" },
    seloPosto(posto),
    el(
      "span",
      { classe: "celula-principal" },
      el("strong", { classe: "militar__guerra" }, String(guerra ?? "").toUpperCase()),
      sub ? el("span", {}, sub) : null,
    ),
  );
}

export function selo(texto, tipo = "neutro", semPonto = false) {
  const classes = ["selo"];
  if (tipo !== "neutro") classes.push(`selo--${tipo}`);
  if (semPonto) classes.push("selo--sem-ponto");
  return el("span", { classe: classes.join(" ") }, texto);
}

export const SITUACOES_ESTOQUE = {
  NORMAL: ["Normal", "ok"],
  ABAIXO_DO_MINIMO: ["Abaixo do mínimo", "atencao"],
  CRITICO: ["Crítico", "perigo"],
  SEM_ESTOQUE: ["Sem estoque", "perigo"],
};
export const seloEstoque = (situacao) => {
  const [texto, tipo] = SITUACOES_ESTOQUE[situacao] ?? [situacao, "neutro"];
  return selo(texto, tipo);
};

export const STATUS_UNIDADE = {
  DISPONIVEL: ["Disponível", "ok"],
  CAUTELADA: ["Em posse", "atencao"],
  EM_MANUTENCAO: ["Em manutenção", "info"],
  NAO_LOCALIZADA: ["Não localizada", "perigo"],
  BAIXA_PENDENTE: ["Baixa pendente", "neutro"],
  BAIXADA: ["Baixada", "neutro"],
  AGUARDANDO_TOMBAMENTO: ["Sem tombamento", "neutro"],
};
export const seloStatus = (status) => {
  const [texto, tipo] = STATUS_UNIDADE[status] ?? [status, "neutro"];
  return selo(texto, tipo);
};

export const TIPOS_MOVIMENTO = {
  RETIRADA: ["Retirada", "atencao", "retirada", "saida"],
  DEVOLUCAO: ["Devolução", "ok", "devolucao", "entrada"],
  ENTRADA: ["Entrada", "info", "pacote-mais", "info"],
  MUDANCA_STATUS: ["Situação", "neutro", "ferramenta", ""],
  AJUSTE: ["Ajuste", "neutro", "editar", ""],
  ESTORNO: ["Estorno", "perigo", "recarregar", "perigo"],
};
export const seloTipo = (tipo) => {
  const [texto, cor] = TIPOS_MOVIMENTO[tipo] ?? [tipo, "neutro"];
  return selo(texto, cor, true);
};

export const ESTADOS = {
  BOM: ["Bom", "ok"],
  REGULAR: ["Regular", "atencao"],
  AVARIADO: ["Avariado", "atencao"],
  INSERVIVEL: ["Inservível", "perigo"],
};
export const seloEstado = (estado) => {
  if (!estado) return null;
  const [texto, tipo] = ESTADOS[estado] ?? [estado, "neutro"];
  return selo(texto, tipo);
};

export const PERFIS = {
  ADMINISTRADOR: ["Administrador", "ok"],
  ESTOQUISTA: ["Estoquista", "info"],
  EQUIPAMENTISTA: ["Equipamentista", "atencao"],
  CONSULTA: ["Consulta", "neutro"],
};
export const seloPerfil = (perfil) => {
  const [texto, tipo] = PERFIS[perfil] ?? [perfil, "neutro"];
  return selo(texto, tipo, true);
};

const DUAS_HORAS = 2 * 60 * 60 * 1000;
/** Situação de uma posse pelo prazo: sempre com texto; a cor só reforça. */
export function situacaoPrazo(prazoIso) {
  const falta = new Date(prazoIso).getTime() - Date.now();
  if (falta < 0) return { tipo: "perigo", texto: `Vencida há ${duracao(falta)}`, vencida: true };
  if (falta < DUAS_HORAS) return { tipo: "atencao", texto: `Vence em ${duracao(falta)}` };
  return { tipo: "ok", texto: `No prazo · ${duracao(falta)}` };
}
export const seloPrazo = (prazoIso) => {
  const s = situacaoPrazo(prazoIso);
  return selo(s.texto, s.tipo);
};

// ------------------------------------------------------------ avisos (toasts)
export function avisar(texto, { erro = false, titulo } = {}) {
  const aviso = el(
    "div",
    { classe: `aviso${erro ? " aviso--erro" : ""}`, role: erro ? "alert" : "status" },
    icone(erro ? "alerta" : "ok-circulo"),
    el("div", {}, titulo ? el("strong", {}, titulo) : null, texto),
  );
  $("avisos").append(aviso);
  setTimeout(() => aviso.remove(), erro ? 7000 : 4500);
}

// ------------------------------------------------------------ estados de página
export function esqueleto(linhas = 5) {
  return el(
    "div",
    { classe: "esqueleto", "aria-busy": "true", "aria-label": "Carregando" },
    Array.from({ length: linhas }, (_, i) =>
      el("div", {
        classe: `esqueleto__linha${i % 3 === 2 ? " esqueleto__linha--curta" : i % 3 === 1 ? " esqueleto__linha--media" : ""}`,
      }),
    ),
  );
}

export function vazio({ icone: nome = "caixa", titulo, texto, acao } = {}) {
  return el(
    "div",
    { classe: "vazio" },
    el("div", { classe: "vazio__icone" }, icone(nome, "icone--24")),
    titulo ? el("strong", {}, titulo) : null,
    texto ? el("span", {}, texto) : null,
    acao ?? null,
  );
}

// ------------------------------------------------------------ botões
export function botao(
  texto,
  { classe = "secundario", iconeNome, tipo = "button", aoClicar, ...resto } = {},
) {
  return el(
    "button",
    {
      classe: `botao botao--${classe.split(" ").join(" botao--")}`,
      type: tipo,
      onclick: aoClicar,
      ...resto,
    },
    iconeNome ? icone(iconeNome, "icone--16") : null,
    texto ? el("span", {}, texto) : null,
  );
}

/** Desabilita o botão e mostra o giro enquanto a promessa não termina. */
export async function comCarregamento(botaoAlvo, trabalho) {
  if (!botaoAlvo) return trabalho();
  const conteudo = [...botaoAlvo.childNodes];
  botaoAlvo.disabled = true;
  botaoAlvo.replaceChildren(
    el("span", { classe: "giro", "aria-hidden": "true" }),
    el("span", {}, "Aguarde…"),
  );
  try {
    return await trabalho();
  } finally {
    botaoAlvo.replaceChildren(...conteudo);
    botaoAlvo.disabled = false;
  }
}

// ------------------------------------------------------------ campos de formulário
export function campo({ rotulo, opcional = false, ajuda, controle, nome }) {
  const id = controle.id || `c-${nome ?? Math.random().toString(36).slice(2)}`;
  controle.id = id;
  const erro = el("span", { classe: "campo__erro", hidden: true, id: `${id}-erro` });
  controle.setAttribute("aria-describedby", `${id}-erro`);
  return el(
    "div",
    { classe: "campo", "data-campo": nome ?? "" },
    el(
      "label",
      { classe: "campo__rotulo", for: id },
      rotulo,
      opcional ? el("span", { classe: "opcional" }, " (opcional)") : null,
    ),
    controle,
    ajuda ? el("span", { classe: "campo__ajuda" }, ajuda) : null,
    erro,
  );
}

export function entrada({
  nome,
  valor = "",
  tipo = "text",
  max,
  min,
  placeholder,
  obrigatorio,
  passo,
  modo,
  auto = "off",
}) {
  return el("input", {
    classe: "entrada",
    name: nome,
    type: tipo,
    valor: valor ?? "",
    maxlength: tipo === "text" || tipo === "password" ? max : undefined,
    max: tipo === "number" || tipo === "date" ? max : undefined,
    min,
    step: passo,
    placeholder,
    required: obrigatorio,
    inputmode: modo,
    autocomplete: auto,
  });
}

export function selecao({ nome, opcoes, valor, vazia }) {
  const controle = el("select", { classe: "selecao", name: nome });
  if (vazia !== undefined) controle.append(el("option", { value: "" }, vazia));
  for (const opcao of opcoes) {
    if (opcao.grupo) {
      const grupo = el("optgroup", { label: opcao.grupo });
      for (const o of opcao.opcoes) grupo.append(el("option", { value: o.valor }, o.texto));
      controle.append(grupo);
    } else {
      controle.append(el("option", { value: opcao.valor }, opcao.texto));
    }
  }
  if (valor !== undefined && valor !== null) controle.value = String(valor);
  return controle;
}

export function area({ nome, valor = "", max = 500, placeholder }) {
  return el(
    "textarea",
    { classe: "area", name: nome, maxlength: max, placeholder, rows: 3 },
    valor ?? "",
  );
}

/** Segmentado (rádios estilizados): [{valor, texto, ponto}] */
export function segmentado({ nome, opcoes, valor, rotulo }) {
  return el(
    "div",
    { classe: "segmentado", role: "radiogroup", "aria-label": rotulo },
    opcoes.map((o) =>
      el(
        "label",
        {},
        el("input", { type: "radio", name: nome, value: o.valor, marcado: o.valor === valor }),
        el("span", {}, o.ponto ? el("i", { classe: `ponto ponto--${o.ponto}` }) : null, o.texto),
      ),
    ),
  );
}

export function valorMarcado(raiz, nome) {
  return raiz.querySelector(`input[name="${nome}"]:checked`)?.value ?? null;
}

/** Marca o campo com erro (a API devolve o nome do campo nos 400). */
export function mostrarErroCampo(formulario, nome, mensagem) {
  limparErros(formulario);
  const bloco = formulario.querySelector(`[data-campo="${CSS.escape(nome)}"]`);
  if (!bloco) return false;
  const erro = bloco.querySelector(".campo__erro");
  erro.textContent = mensagem;
  erro.hidden = false;
  const controle = bloco.querySelector("input, select, textarea");
  controle?.setAttribute("aria-invalid", "true");
  controle?.focus();
  return true;
}

export function limparErros(formulario) {
  for (const erro of formulario.querySelectorAll(".campo__erro")) {
    erro.hidden = true;
    erro.textContent = "";
  }
  for (const c of formulario.querySelectorAll("[aria-invalid]")) c.removeAttribute("aria-invalid");
}

// ------------------------------------------------------------ tabela responsiva
/**
 * colunas: [{ titulo, classe, rotulo, principal, render(linha) }]. No celular a linha vira
 * cartão: a coluna `principal` é o título do cartão e as outras mostram o rótulo.
 */
export function tabela({ colunas, linhas, aoClicar, classeLinha, rotuloLinha }) {
  const corpo = el("tbody");
  for (const linha of linhas) {
    const tr = el("tr", {
      classe:
        [aoClicar ? "clicavel" : "", classeLinha?.(linha) ?? ""].join(" ").trim() || undefined,
      tabindex: aoClicar ? "0" : undefined,
      "aria-label": aoClicar && rotuloLinha ? rotuloLinha(linha) : undefined,
    });
    for (const coluna of colunas) {
      tr.append(
        el(
          "td",
          {
            classe:
              [coluna.classe, coluna.principal ? "cartao-titulo" : ""].join(" ").trim() ||
              undefined,
            "data-rotulo": coluna.rotulo ?? coluna.titulo ?? "",
          },
          coluna.render(linha),
        ),
      );
    }
    if (aoClicar) {
      tr.addEventListener("click", (evento) => {
        if (evento.target.closest("button, a, input, label")) return;
        aoClicar(linha);
      });
      tr.addEventListener("keydown", (evento) => {
        if (evento.key === "Enter" && evento.target === tr) aoClicar(linha);
      });
    }
    corpo.append(tr);
  }
  return el(
    "div",
    { classe: "tabela-rolagem" },
    el(
      "table",
      { classe: "tabela tabela--cartoes" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          colunas.map((c) => el("th", { classe: c.classe, scope: "col" }, c.titulo ?? "")),
        ),
      ),
      corpo,
    ),
  );
}

// ------------------------------------------------------------ diálogo (modal)
/**
 * Abre um <dialog> nativo (foco preso, Esc fecha). `formulario: true` faz do corpo um
 * <form>: Enter envia e o botão do tipo submit chama aoEnviar(form, botao).
 */
export function dialogo({
  titulo,
  subtitulo,
  corpo,
  acoes = [],
  largo = false,
  aoEnviar,
  aoFechar,
}) {
  const caixa = el("dialog", {
    classe: `dialogo${largo ? " dialogo--largo" : ""}`,
    "aria-labelledby": "dialogo-titulo",
  });
  const fechar = () => caixa.close();
  const cabeca = el(
    "div",
    { classe: "dialogo__cabeca" },
    el(
      "div",
      {},
      el("h2", { id: "dialogo-titulo" }, titulo),
      subtitulo ? el("p", {}, subtitulo) : null,
    ),
    botao("", {
      classe: "fantasma icone",
      iconeNome: "fechar",
      "aria-label": "Fechar",
      aoClicar: fechar,
    }),
  );
  const pe = el(
    "div",
    { classe: "dialogo__pe" },
    acoes.map((a) =>
      botao(a.texto, {
        classe: a.classe ?? "secundario",
        tipo: a.tipo ?? "button",
        iconeNome: a.icone,
        aoClicar: a.tipo === "submit" ? undefined : (a.aoClicar ?? fechar),
      }),
    ),
  );
  const miolo = el("div", { classe: "dialogo__corpo" }, corpo);
  if (aoEnviar) {
    const form = el(
      "form",
      { novalidate: true, classe: "dialogo__form" },
      miolo,
      acoes.length ? pe : null,
    );
    form.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const botaoEnviar = form.querySelector("button[type=submit]");
      await comCarregamento(botaoEnviar, () => aoEnviar(form, { fechar }));
    });
    caixa.append(cabeca, form);
  } else {
    caixa.append(cabeca, miolo, acoes.length ? pe : null);
  }
  caixa.addEventListener("close", () => {
    caixa.remove();
    aoFechar?.();
  });
  caixa.addEventListener("click", (evento) => {
    if (evento.target === caixa) fechar(); // clique fora (no fundo) fecha
  });
  document.body.append(caixa);
  caixa.showModal();
  caixa.querySelector("input:not([type=hidden]), select, textarea")?.focus();
  return { caixa, fechar, corpo: miolo };
}

export function confirmar({ titulo, texto, botaoTexto = "Confirmar", perigo = false }) {
  return new Promise((resolver) => {
    let resposta = false;
    dialogo({
      titulo,
      corpo: el("p", { classe: "texto-2" }, texto),
      acoes: [
        { texto: "Cancelar" },
        {
          texto: botaoTexto,
          classe: perigo ? "perigo" : "primario",
          aoClicar: () => {
            resposta = true;
            document.querySelector("dialog[open]")?.close();
          },
        },
      ],
      aoFechar: () => resolver(resposta),
    });
  });
}

// ------------------------------------------------------------ painel lateral
let painelAberto = null;
export function painel({ titulo, subtitulo, corpo }) {
  fecharPainel();
  const veu = el("div", { classe: "veu", onclick: () => fecharPainel() });
  const caixa = el(
    "aside",
    { classe: "painel", role: "dialog", "aria-modal": "true", "aria-label": titulo },
    el(
      "div",
      { classe: "painel__cabeca" },
      el(
        "div",
        {},
        el("h2", {}, titulo),
        subtitulo ? el("p", { classe: "texto-3 pequeno" }, subtitulo) : null,
      ),
      botao("", {
        classe: "fantasma icone",
        iconeNome: "fechar",
        "aria-label": "Fechar",
        aoClicar: () => fecharPainel(),
      }),
    ),
    el("div", { classe: "painel__corpo" }, corpo),
  );
  const aoTeclar = (evento) => {
    if (evento.key === "Escape" && !document.querySelector("dialog[open]")) fecharPainel();
  };
  document.addEventListener("keydown", aoTeclar);
  document.body.append(veu, caixa);
  caixa.querySelector("button")?.focus();
  painelAberto = { veu, caixa, aoTeclar };
  return { fechar: fecharPainel, corpo: caixa.querySelector(".painel__corpo") };
}

export function fecharPainel() {
  if (!painelAberto) return;
  painelAberto.veu.remove();
  painelAberto.caixa.remove();
  document.removeEventListener("keydown", painelAberto.aoTeclar);
  painelAberto = null;
}

// ------------------------------------------------------------ busca com resultados
/** Busca com "senha": se o usuário digitar rápido, só a resposta da última busca vale. */
export function busca({ entrada: alvo, lista, buscar, desenhar, minimo = 2, aoErro }) {
  let ultima = 0;
  const executar = aoParar(async () => {
    const termo = alvo.value.trim();
    const minha = ++ultima;
    if (termo.length < minimo) {
      lista.replaceChildren();
      return;
    }
    try {
      const itens = await buscar(termo);
      if (minha !== ultima) return;
      lista.replaceChildren(
        ...(itens.length === 0
          ? [el("li", { classe: "resultados__nota" }, "Nada encontrado.")]
          : itens.map((item) => el("li", {}, desenhar(item)))),
      );
    } catch (erro) {
      if (minha === ultima) aoErro?.(erro);
    }
  });
  alvo.addEventListener("input", executar);
  return { limpar: () => lista.replaceChildren() };
}

export function campoBusca({ placeholder, rotulo, nome = "busca" }) {
  const controle = el("input", {
    classe: "entrada",
    type: "search",
    name: nome,
    placeholder,
    autocomplete: "off",
    "aria-label": rotulo ?? placeholder,
    spellcheck: "false",
  });
  return { bloco: el("div", { classe: "busca" }, icone("busca"), controle), controle };
}

export function cartao({ titulo, sub, acoes, corpo, semPadding = false, pe }) {
  return el(
    "section",
    { classe: "cartao" },
    titulo
      ? el(
          "div",
          { classe: "cartao__cabeca" },
          el("div", {}, el("h2", {}, titulo), sub ? el("p", { classe: "cartao__sub" }, sub) : null),
          acoes ? el("div", { classe: "linha-acoes" }, acoes) : null,
        )
      : null,
    el("div", { classe: `cartao__corpo${semPadding ? " cartao__corpo--sem" : ""}` }, corpo),
    pe ? el("div", { classe: "cartao__pe" }, pe) : null,
  );
}

export function cabecalhoPagina({ titulo, texto, acoes }) {
  return el(
    "div",
    { classe: "cabecalho-pagina" },
    el(
      "div",
      { classe: "cabecalho-pagina__texto" },
      el("h2", {}, titulo),
      texto ? el("p", {}, texto) : null,
    ),
    acoes ? el("div", { classe: "cabecalho-pagina__acoes" }, acoes) : null,
  );
}
