// Início: o que o balcão precisa saber agora. Sem gráfico (as análises ficam no Power BI):
// contadores com o próximo passo, as posses vencidas e as últimas movimentações.

import { pedir } from "../api.js";
import { contexto, OPERACIONAIS, pode } from "../contexto.js";
import {
  cartao,
  dataHoraCurta,
  el,
  icone,
  militar,
  numero,
  rotuloMilitar,
  seloPrazo,
  TIPOS_MOVIMENTO,
  vazio,
} from "../ui.js";
import { abrirCiclo } from "./historico.js";

function saudacao() {
  const hora = Number(
    new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Recife",
      hour: "numeric",
      hour12: false,
    }).format(new Date()),
  );
  if (hora < 12) return "Bom dia";
  if (hora < 18) return "Boa tarde";
  return "Boa noite";
}

function indicador({ rotulo, valor, nota, iconeNome, tipo, rota, parametros }) {
  const corpo = [
    el(
      "div",
      { classe: "indicador__topo" },
      el("span", {}, rotulo),
      el("span", { classe: "indicador__icone" }, icone(iconeNome)),
    ),
    el("div", { classe: "indicador__valor" }, numero(valor)),
    el("div", { classe: "indicador__nota" }, nota),
  ];
  const classe = `indicador${tipo ? ` indicador--${tipo}` : ""}`;
  if (!rota) return el("div", { classe }, corpo);
  const busca = new URLSearchParams(parametros ?? {}).toString();
  return el("a", { classe, href: `#/${rota}${busca ? `?${busca}` : ""}` }, corpo);
}

function acaoRapida({ titulo, texto, iconeNome, rota, clara }) {
  return el(
    "a",
    { classe: `acao-rapida${clara ? " acao-rapida--clara" : ""}`, href: `#/${rota}` },
    el("span", { classe: "acao-rapida__icone" }, icone(iconeNome, "icone--24")),
    el("div", {}, el("strong", {}, titulo), el("span", { classe: "acao-rapida__sub" }, texto)),
    icone("seta", "seta"),
  );
}

export function linhaMovimento(m) {
  const [rotulo, , nomeIcone, marcador] = TIPOS_MOVIMENTO[m.tipo] ?? [m.tipo, "", "lista", ""];
  const quem = m.posto ? rotuloMilitar(m.posto, m.nome_guerra) : null;
  const responsavel = rotuloMilitar(m.executor_posto, m.executor_guerra);
  return el(
    "button",
    {
      classe: "lista__item lista__item--botao",
      type: "button",
      onclick: () => abrirCiclo(m),
      "aria-label": `${rotulo}: ${m.material}`,
    },
    el("span", { classe: `marcador${marcador ? ` marcador--${marcador}` : ""}` }, icone(nomeIcone)),
    el(
      "span",
      { classe: "lista__principal" },
      el(
        "span",
        { classe: "lista__titulo" },
        `${m.quantidade > 1 ? `${m.quantidade}× ` : ""}${m.material}`,
      ),
      el(
        "span",
        { classe: "lista__sub" },
        [
          rotulo,
          quem && (m.tipo === "DEVOLUCAO" ? `de ${quem}` : `com ${quem}`),
          `por ${responsavel}`,
        ]
          .filter(Boolean)
          .join(" · "),
      ),
    ),
    el(
      "span",
      { classe: "lista__lado" },
      el("span", { classe: "pequeno texto-3" }, dataHoraCurta(m.ocorrida_em)),
    ),
  );
}

export async function renderizar(alvo) {
  const { contadores, vencidas, ultimas } = await pedir("GET", "/resumo");
  const u = contexto.usuario;
  const operacional = pode(OPERACIONAIS);

  const acoes = operacional
    ? el(
        "div",
        { classe: "acoes-rapidas" },
        acaoRapida({
          titulo: "Nova retirada",
          texto: "Entregar material a um militar",
          iconeNome: "retirada",
          rota: "retirada",
        }),
        acaoRapida({
          titulo: "Receber devolução",
          texto: "Conferir o estado e dar baixa na posse",
          iconeNome: "devolucao",
          rota: "devolucao",
          clara: true,
        }),
        acaoRapida({
          titulo: "Consultar estoque",
          texto: "Disponível, em posse e em manutenção",
          iconeNome: "estoque",
          rota: "estoque",
          clara: true,
        }),
      )
    : el(
        "div",
        { classe: "alerta alerta--info" },
        icone("info"),
        el(
          "span",
          {},
          "Perfil de consulta: você acompanha posse, estoque e histórico, mas não registra movimentações.",
        ),
      );

  const indicadores = el(
    "div",
    { classe: "indicadores" },
    indicador({
      rotulo: "Em posse agora",
      valor: contadores.em_posse,
      nota: `com ${numero(contadores.militares_com_material)} militar(es)`,
      iconeNome: "posse",
      rota: "posse",
    }),
    indicador({
      rotulo: "Posses vencidas",
      valor: contadores.vencidas,
      nota: contadores.vencidas ? "cobrar a devolução" : "nenhuma pendência",
      iconeNome: "alerta",
      tipo: contadores.vencidas ? "perigo" : undefined,
      rota: "posse",
      parametros: { situacao: "vencidas" },
    }),
    indicador({
      rotulo: "Estoque em alerta",
      valor: contadores.abaixo_do_minimo,
      nota: "abaixo do mínimo ou zerado",
      iconeNome: "estoque",
      tipo: contadores.abaixo_do_minimo ? "atencao" : undefined,
      rota: "estoque",
      parametros: { situacao: "alerta" },
    }),
    indicador({
      rotulo: "Em manutenção",
      valor: contadores.em_manutencao,
      nota: "unidades fora de uso",
      iconeNome: "ferramenta",
      tipo: "info",
      rota: "estoque",
    }),
    indicador({
      rotulo: "Hoje",
      valor: contadores.retiradas_hoje + contadores.devolucoes_hoje,
      nota: `${numero(contadores.retiradas_hoje)} retirada(s) · ${numero(contadores.devolucoes_hoje)} devolução(ões)`,
      iconeNome: "relogio",
      rota: "historico",
    }),
  );

  const listaVencidas =
    vencidas.length === 0
      ? vazio({
          icone: "ok-circulo",
          titulo: "Nenhuma posse vencida",
          texto: "Tudo dentro do prazo.",
        })
      : el(
          "ul",
          { classe: "lista" },
          vencidas.map((g) =>
            el(
              "li",
              { classe: "lista__item" },
              militar(g.posto, g.nome_guerra, g.setor),
              el(
                "span",
                { classe: "lista__principal" },
                el(
                  "span",
                  { classe: "lista__titulo" },
                  `${g.quantidade > 1 ? `${g.quantidade}× ` : ""}${g.material}`,
                ),
                el(
                  "span",
                  { classe: "lista__sub" },
                  `Retirada ${dataHoraCurta(g.retirada_em)} · ${rotuloMilitar(g.entregue_por_posto, g.entregue_por_guerra)}`,
                ),
              ),
              el("span", { classe: "lista__lado" }, seloPrazo(g.prazo)),
            ),
          ),
        );

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, `${saudacao()}, ${rotuloMilitar(u.posto, u.nome_guerra)}`),
        el("p", {}, "Resumo do almoxarifado e da reserva de equipamentos."),
      ),
    ),
    acoes,
    indicadores,
    el(
      "div",
      { classe: "duas-colunas" },
      cartao({
        titulo: "Posses vencidas",
        sub: "As mais antigas primeiro",
        acoes: el(
          "a",
          { classe: "botao botao--fantasma botao--pequeno", href: "#/posse?situacao=vencidas" },
          "Ver todas",
          icone("direita", "icone--16"),
        ),
        corpo: listaVencidas,
        semPadding: true,
      }),
      cartao({
        titulo: "Últimas movimentações",
        sub: "Toque para ver o ciclo completo",
        acoes: el(
          "a",
          { classe: "botao botao--fantasma botao--pequeno", href: "#/historico" },
          "Histórico",
          icone("direita", "icone--16"),
        ),
        corpo:
          ultimas.length === 0
            ? vazio({ icone: "historico", titulo: "Sem movimentações ainda" })
            : el("div", { classe: "lista" }, ultimas.map(linhaMovimento)),
        semPadding: true,
      }),
    ),
  );
}
