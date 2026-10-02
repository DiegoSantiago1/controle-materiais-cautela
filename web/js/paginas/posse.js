// Em posse: o que está com cada militar agora, agrupado por atendimento. Vencidas primeiro.

import { pedir } from "../api.js";
import { irPara, OPERACIONAIS, pode, referencias } from "../contexto.js";
import {
  botao,
  campoBusca,
  dataHora,
  el,
  militar,
  normalizar,
  numero,
  rotuloMilitar,
  selecao,
  selo,
  seloPrazo,
  situacaoPrazo,
  tabela,
  vazio,
} from "../ui.js";
import { abrirCiclo } from "./historico.js";

export async function renderizar(alvo, parametros) {
  const [{ grupos }, refs] = await Promise.all([pedir("GET", "/posse"), referencias()]);

  const buscaTexto = campoBusca({ placeholder: "Militar, material, BMP ou quem entregou" });
  buscaTexto.controle.value = parametros.busca ?? "";
  const situacao = selecao({
    nome: "situacao",
    valor: parametros.situacao ?? "",
    vazia: "Todas as situações",
    opcoes: [
      { valor: "vencidas", texto: "Vencidas" },
      { valor: "no_prazo", texto: "No prazo" },
    ],
  });
  const categoria = selecao({
    nome: "categoria",
    vazia: "Todas as categorias",
    opcoes: refs.categorias.map((c) => ({ valor: c.nome, texto: c.nome })),
  });
  const setor = selecao({
    nome: "setor",
    vazia: "Todos os setores",
    opcoes: refs.setores.map((s) => ({ valor: s.sigla, texto: `${s.sigla} · ${s.nome}` })),
  });
  const total = el("span", { classe: "filtros__total" });
  const corpo = el("div", {});
  const operacional = pode(OPERACIONAIS);

  function desenhar() {
    const termo = normalizar(buscaTexto.controle.value);
    const filtrados = grupos.filter((g) => {
      if (situacao.value === "vencidas" && !g.vencida) return false;
      if (situacao.value === "no_prazo" && g.vencida) return false;
      if (categoria.value && g.categoria !== categoria.value) return false;
      if (setor.value && g.setor !== setor.value) return false;
      if (!termo) return true;
      const texto = [
        rotuloMilitar(g.posto, g.nome_guerra),
        g.nome,
        g.matricula,
        g.material,
        g.codigo,
        rotuloMilitar(g.entregue_por_posto, g.entregue_por_guerra),
        ...g.unidades.map((u) => u.bmp),
      ].join(" ");
      return normalizar(texto).includes(termo);
    });
    const unidades = filtrados.reduce((s, g) => s + g.quantidade, 0);
    total.textContent = `${numero(filtrados.length)} registro(s) · ${numero(unidades)} unidade(s)`;
    if (filtrados.length === 0) {
      corpo.replaceChildren(
        vazio({
          icone: grupos.length ? "busca" : "ok-circulo",
          titulo: grupos.length ? "Nada encontrado com esses filtros" : "Nenhum material em posse",
          texto: grupos.length
            ? "Limpe a busca ou troque a situação."
            : "Todo o material está no almoxarifado.",
        }),
      );
      return;
    }
    corpo.replaceChildren(
      tabela({
        linhas: filtrados,
        classeLinha: (g) => (g.vencida ? "linha--alerta" : ""),
        aoClicar: (g) =>
          abrirCiclo({ operacao: g.operacao, primeiro_id: g.retirada_id, material: g.material }),
        rotuloLinha: (g) => `${g.material} com ${rotuloMilitar(g.posto, g.nome_guerra)}`,
        colunas: [
          {
            titulo: "Militar",
            principal: true,
            render: (g) => militar(g.posto, g.nome_guerra, `${g.setor} · mat. ${g.matricula}`),
          },
          {
            titulo: "Material",
            render: (g) =>
              el(
                "div",
                { classe: "celula-principal" },
                el("strong", {}, g.material),
                el(
                  "span",
                  {},
                  g.unidades.length <= 4
                    ? g.unidades.map((u) => u.bmp).join(", ")
                    : `${g.codigo} · ${g.unidades.length} BMPs`,
                ),
              ),
          },
          {
            titulo: "Qtd",
            classe: "direita estreita",
            render: (g) => el("span", { classe: "valor-destaque" }, numero(g.quantidade)),
          },
          { titulo: "Retirada", classe: "estreita", render: (g) => dataHora(g.retirada_em) },
          {
            titulo: "Entregue por",
            classe: "estreita",
            render: (g) => rotuloMilitar(g.entregue_por_posto, g.entregue_por_guerra),
          },
          {
            titulo: "Prazo",
            classe: "estreita",
            render: (g) =>
              el(
                "div",
                { classe: "celula-principal" },
                seloPrazo(g.prazo),
                el("span", {}, dataHora(g.prazo)),
              ),
          },
          {
            titulo: "",
            rotulo: "",
            classe: "estreita direita",
            render: (g) =>
              el(
                "div",
                { classe: "linha-acoes" },
                g.estado_retirada === "REGULAR" ? selo("Saiu regular", "atencao") : null,
                operacional
                  ? botao("Receber", {
                      classe: "suave pequeno",
                      iconeNome: "devolucao",
                      aoClicar: () =>
                        irPara("devolucao", { pessoa: g.pessoa_id, operacao: g.operacao }),
                    })
                  : null,
              ),
          },
        ],
      }),
    );
  }

  for (const controle of [buscaTexto.controle, situacao, categoria, setor]) {
    controle.addEventListener("input", desenhar);
  }

  const vencidas = grupos.filter((g) => situacaoPrazo(g.prazo).vencida).length;
  const militares = new Set(grupos.map((g) => g.pessoa_id)).size;
  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Material em posse"),
        el(
          "p",
          {},
          `${numero(militares)} militar(es) com material · ${numero(vencidas)} retirada(s) com prazo vencido`,
        ),
      ),
      operacional
        ? el(
            "div",
            { classe: "cabecalho-pagina__acoes" },
            el("a", { classe: "botao botao--primario", href: "#/devolucao" }, "Receber devolução"),
          )
        : null,
    ),
    el(
      "section",
      { classe: "cartao" },
      el("div", { classe: "filtros" }, buscaTexto.bloco, situacao, categoria, setor, total),
      corpo,
    ),
  );
  desenhar();
}
