// Histórico de movimentações (agrupado por atendimento) e o ciclo de cada atendimento:
// retirada -> posse -> devolução, com quem entregou e quem recebeu.

import { consulta, pedir } from "../api.js";
import { tratarErro } from "../contexto.js";
import {
  botao,
  campoBusca,
  comCarregamento,
  dataHora,
  duracao,
  el,
  entrada,
  esqueleto,
  icone,
  militar,
  numero,
  painel,
  rotuloMilitar,
  selecao,
  selo,
  seloEstado,
  seloStatus,
  seloTipo,
  TIPOS_MOVIMENTO,
  tabela,
  vazio,
} from "../ui.js";

// ------------------------------------------------------------ ciclo (painel lateral)
const maiusculo = (texto) => String(texto ?? "—").toUpperCase();
function passo({ tipo, titulo, detalhe, extra }) {
  return el(
    "li",
    {},
    el(
      "span",
      { classe: `linha-tempo__ponto linha-tempo__ponto--${tipo}` },
      icone(
        { saida: "retirada", posse: "relogio", entrada: "devolucao", outro: "ferramenta" }[tipo],
        "icone--16",
      ),
    ),
    el(
      "div",
      {},
      el("div", { classe: "linha-tempo__titulo" }, titulo),
      el("div", { classe: "linha-tempo__detalhe" }, detalhe),
      extra ?? null,
    ),
  );
}

function cicloDaUnidade(item) {
  const r = item.retirada;
  const f = item.fechamento;
  const passos = [];
  if (r?.id) {
    passos.push(
      passo({
        tipo: "saida",
        titulo: `Retirada por ${maiusculo(r.militar)}`,
        detalhe: `${dataHora(r.em)} · entregue por ${maiusculo(r.entregue_por)}${r.finalidade ? ` · ${r.finalidade}` : ""}`,
        extra: el(
          "div",
          { classe: "linha-acoes" },
          seloEstado(r.estado),
          r.observacao ? el("span", { classe: "pequeno texto-3" }, r.observacao) : null,
        ),
      }),
    );
    const fim = f ? new Date(f.em) : new Date();
    passos.push(
      passo({
        tipo: "posse",
        titulo: f
          ? `Em posse por ${duracao(fim - new Date(r.em))}`
          : `Em posse há ${duracao(fim - new Date(r.em))}`,
        detalhe: `Prazo de devolução: ${dataHora(r.prazo)}${!f && new Date(r.prazo) < new Date() ? " (vencido)" : ""}`,
      }),
    );
  }
  if (f) {
    const devolucao = f.tipo === "DEVOLUCAO";
    passos.push(
      passo({
        tipo: devolucao ? "entrada" : "outro",
        titulo: devolucao
          ? `Devolvida por ${maiusculo(f.militar)}`
          : f.tipo === "ESTORNO"
            ? "Retirada estornada"
            : "Mudança de situação",
        detalhe: `${dataHora(f.em)} · ${devolucao ? "recebida" : "registrada"} por ${maiusculo(f.recebido_por)}`,
        extra: el(
          "div",
          { classe: "linha-acoes" },
          devolucao ? seloEstado(f.estado) : seloStatus(f.status_novo),
          f.observacao ? el("span", { classe: "pequeno texto-3" }, f.observacao) : null,
        ),
      }),
    );
  } else if (r?.id) {
    passos.push(
      passo({ tipo: "outro", titulo: "Ainda não devolvida", detalhe: "A posse continua aberta." }),
    );
  }
  return el(
    "div",
    { classe: "ciclo__unidade" },
    el(
      "div",
      { classe: "linha-acoes" },
      el("strong", {}, item.material),
      item.bmp ? el("span", { classe: "chip" }, `BMP ${item.bmp}`) : null,
      item.controle === "CONSUMO" ? selo(`${item.quantidade} (consumo)`, "neutro", true) : null,
    ),
    passos.length
      ? el("ol", { classe: "linha-tempo" }, passos)
      : el(
          "p",
          { classe: "texto-3 pequeno" },
          "Movimento sem ciclo de posse (entrada, ajuste ou situação).",
        ),
  );
}

/** Abre o ciclo de um atendimento (pela operação) ou de uma movimentação avulsa. */
export async function abrirCiclo(m) {
  const { corpo } = painel({
    titulo: "Ciclo do material",
    subtitulo: m.material
      ? `${m.quantidade > 1 ? `${m.quantidade}× ` : ""}${m.material}`
      : undefined,
  });
  corpo.replaceChildren(esqueleto(6));
  try {
    const parametros = m.operacao
      ? { operacao: m.operacao }
      : { movimentacao: m.primeiro_id ?? m.ultimo_id };
    const { itens } = await pedir("GET", `/ciclo${consulta(parametros)}`);
    corpo.replaceChildren(
      m.operacao ? el("p", { classe: "mono pequeno texto-3" }, `Operação ${m.operacao}`) : null,
      el("div", { classe: "ciclo" }, itens.map(cicloDaUnidade)),
    );
  } catch (erro) {
    corpo.replaceChildren(vazio({ icone: "alerta", titulo: "Não foi possível carregar o ciclo" }));
    tratarErro(erro);
  }
}

// ------------------------------------------------------------ página
export async function renderizar(alvo, parametros) {
  const buscaTexto = campoBusca({ placeholder: "Material, BMP, militar ou responsável" });
  buscaTexto.controle.value = parametros.busca ?? "";
  const tipo = selecao({
    nome: "tipo",
    vazia: "Todos os tipos",
    valor: parametros.tipo ?? "",
    opcoes: Object.entries(TIPOS_MOVIMENTO).map(([valor, [texto]]) => ({ valor, texto })),
  });
  const de = entrada({ nome: "de", tipo: "date", valor: parametros.de ?? "" });
  const ate = entrada({ nome: "ate", tipo: "date", valor: parametros.ate ?? "" });
  de.setAttribute("aria-label", "De");
  ate.setAttribute("aria-label", "Até");
  const limpar = botao("Limpar", {
    classe: "fantasma pequeno",
    aoClicar: () => {
      buscaTexto.controle.value = "";
      tipo.value = "";
      de.value = "";
      ate.value = "";
      recarregar();
    },
  });
  const corpo = el("div", {}, esqueleto(8));
  const maisBotao = botao("Carregar mais", { classe: "secundario", iconeNome: "historico" });
  const rodape = el("div", { classe: "mais", hidden: true }, maisBotao);
  const linhas = [];
  let cursor = null;

  const colunas = [
    {
      titulo: "Data e hora",
      classe: "estreita",
      principal: true,
      render: (m) =>
        el(
          "div",
          { classe: "celula-principal" },
          el("strong", {}, dataHora(m.ocorrida_em)),
          el("span", {}, seloTipo(m.tipo)),
        ),
    },
    {
      titulo: "Material",
      render: (m) =>
        el(
          "div",
          { classe: "celula-principal" },
          el("strong", {}, m.material),
          el(
            "span",
            {},
            [m.codigo, m.bmp ? `BMP ${m.bmp}` : null, m.documento].filter(Boolean).join(" · "),
          ),
        ),
    },
    {
      titulo: "Qtd",
      classe: "direita estreita",
      render: (m) => el("span", { classe: "valor-destaque" }, numero(m.quantidade)),
    },
    {
      titulo: "Militar",
      render: (m) =>
        m.posto ? militar(m.posto, m.nome_guerra) : el("span", { classe: "texto-3" }, "—"),
    },
    {
      titulo: "Responsável",
      render: (m) =>
        el(
          "div",
          { classe: "celula-principal" },
          el("strong", {}, rotuloMilitar(m.executor_posto, m.executor_guerra)),
          el(
            "span",
            {},
            {
              RETIRADA: "entregou",
              DEVOLUCAO: "recebeu",
              ENTRADA: "deu entrada",
              AJUSTE: "ajustou",
              MUDANCA_STATUS: "alterou",
              ESTORNO: "estornou",
            }[m.tipo] ?? "",
          ),
        ),
    },
    {
      titulo: "Estado / observação",
      render: (m) =>
        el(
          "div",
          { classe: "celula-principal" },
          el(
            "span",
            { classe: "linha-acoes" },
            seloEstado(m.estado_retirada ?? m.estado_devolucao),
            m.tipo === "MUDANCA_STATUS" && m.status_novo ? seloStatus(m.status_novo) : null,
          ),
          m.observacao || m.finalidade ? el("span", {}, m.observacao ?? m.finalidade) : null,
        ),
    },
  ];

  function filtros() {
    return {
      busca: buscaTexto.controle.value.trim(),
      tipo: tipo.value,
      de: de.value,
      ate: ate.value,
    };
  }

  async function carregar(acrescentar) {
    const f = filtros();
    const pagina = await pedir(
      "GET",
      `/movimentacoes${consulta({ ...f, antes_em: acrescentar ? cursor?.em : "", antes_id: acrescentar ? cursor?.id : "" })}`,
    );
    if (!acrescentar) linhas.length = 0;
    linhas.push(...pagina.movimentacoes);
    const ultima = pagina.movimentacoes.at(-1);
    cursor = ultima ? { em: ultima.ocorrida_em, id: ultima.ultimo_id } : null;
    rodape.hidden = !pagina.tem_mais;
    corpo.replaceChildren(
      linhas.length === 0
        ? vazio({
            icone: "historico",
            titulo: "Nenhuma movimentação encontrada",
            texto: "Ajuste o período ou a busca.",
          })
        : tabela({
            linhas,
            colunas,
            aoClicar: abrirCiclo,
            rotuloLinha: (m) => `${m.tipo} ${m.material}`,
          }),
    );
  }

  const recarregar = async () => {
    try {
      await carregar(false);
    } catch (erro) {
      tratarErro(erro);
    }
  };
  maisBotao.addEventListener("click", () =>
    comCarregamento(maisBotao, () => carregar(true).catch(tratarErro)),
  );
  let espera;
  buscaTexto.controle.addEventListener("input", () => {
    clearTimeout(espera);
    espera = setTimeout(recarregar, 350);
  });
  for (const c of [tipo, de, ate]) c.addEventListener("change", recarregar);

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Histórico de movimentações"),
        el(
          "p",
          {},
          "Nada aqui é alterado ou apagado: correções viram um estorno. Toque numa linha para ver o ciclo completo.",
        ),
      ),
    ),
    el(
      "section",
      { classe: "cartao" },
      el("div", { classe: "filtros" }, buscaTexto.bloco, tipo, de, ate, limpar),
      corpo,
      rodape,
    ),
  );
  await carregar(false);
}
