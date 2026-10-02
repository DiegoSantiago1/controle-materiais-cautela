// Receber devolução: escolhe o militar, marca as unidades que ele está devolvendo (pode ser
// parte de uma retirada) e o estado em que voltaram. Quem recebe é quem está logado. A
// retirada original continua no histórico: a devolução é um movimento novo.

import { consulta, ErroApi, pedir } from "../api.js";
import { contexto, tratarErro } from "../contexto.js";
import {
  area,
  avisar,
  botao,
  busca,
  campo,
  campoBusca,
  cartao,
  comCarregamento,
  dataHora,
  dialogo,
  el,
  icone,
  militar,
  rotuloMilitar,
  segmentado,
  selo,
  seloPosto,
  seloPrazo,
  valorMarcado,
  vazio,
} from "../ui.js";

export async function renderizar(alvo, parametros) {
  const estado = { pessoa: null, grupos: [], marcadas: new Set() };

  // ---------------------------------------------------------- militar
  const buscaMilitar = campoBusca({
    placeholder: "Nome de guerra, posto, nome ou matrícula",
    rotulo: "Buscar militar",
  });
  const resultados = el("ul", { classe: "resultados", "aria-label": "Militares encontrados" });
  const escolhido = el("div", { hidden: true });
  const listaPosse = el("div", {});

  busca({
    entrada: buscaMilitar.controle,
    lista: resultados,
    buscar: async (termo) =>
      (await pedir("GET", `/pessoas${consulta({ busca: termo })}`)).pessoas.sort(
        (a, b) => (b.em_posse > 0) - (a.em_posse > 0),
      ),
    desenhar: (p) =>
      el(
        "button",
        {
          classe: "resultado",
          type: "button",
          disabled: p.em_posse === 0,
          onclick: () => escolher(p),
        },
        seloPosto(p.posto),
        el(
          "span",
          { classe: "resultado__texto" },
          el("strong", { classe: "militar__guerra" }, p.nome_guerra.toUpperCase()),
          el("span", { classe: "resultado__sub" }, `${p.nome} · ${p.setor} · mat. ${p.matricula}`),
        ),
        p.em_posse ? selo(`${p.em_posse} em posse`, "atencao") : selo("Nada em posse"),
      ),
    aoErro: tratarErro,
  });

  async function escolher(p) {
    estado.pessoa = p;
    escolhido.replaceChildren(
      el(
        "div",
        { classe: "escolhido" },
        militar(p.posto, p.nome_guerra, `${p.nome} · ${p.setor}`),
        el("span", { classe: "escolhido__texto" }),
        botao("Trocar", { classe: "fantasma pequeno", aoClicar: trocar }),
      ),
    );
    escolhido.hidden = false;
    buscaMilitar.bloco.hidden = true;
    resultados.replaceChildren();
    await carregarPosse();
  }

  function trocar() {
    estado.pessoa = null;
    estado.grupos = [];
    estado.marcadas.clear();
    escolhido.hidden = true;
    buscaMilitar.bloco.hidden = false;
    buscaMilitar.controle.value = "";
    listaPosse.replaceChildren();
    atualizar();
    buscaMilitar.controle.focus();
  }

  async function carregarPosse() {
    listaPosse.replaceChildren(
      el("p", { classe: "texto-3" }, "Carregando o que está com o militar…"),
    );
    try {
      const { grupos } = await pedir("GET", `/posse${consulta({ pessoa_id: estado.pessoa.id })}`);
      estado.grupos = grupos;
      estado.marcadas = new Set(
        parametros.operacao
          ? grupos
              .filter((g) => g.operacao === parametros.operacao)
              .flatMap((g) => g.unidades.map((u) => u.id))
          : grupos.flatMap((g) => g.unidades.map((u) => u.id)),
      );
      desenharPosse();
    } catch (erro) {
      tratarErro(erro);
    }
  }

  function desenharPosse() {
    if (estado.grupos.length === 0) {
      listaPosse.replaceChildren(
        vazio({
          icone: "ok-circulo",
          titulo: "Nada em posse",
          texto: "Este militar não tem material para devolver.",
        }),
      );
      atualizar();
      return;
    }
    const todas = estado.grupos.flatMap((g) => g.unidades.map((u) => u.id));
    listaPosse.replaceChildren(
      el(
        "div",
        { classe: "linha-acoes" },
        botao("Marcar tudo", {
          classe: "fantasma pequeno",
          iconeNome: "ok",
          aoClicar: () => {
            estado.marcadas = new Set(todas);
            desenharPosse();
          },
        }),
        botao("Desmarcar tudo", {
          classe: "fantasma pequeno",
          aoClicar: () => {
            estado.marcadas.clear();
            desenharPosse();
          },
        }),
      ),
      ...estado.grupos.map((g) => {
        const ids = g.unidades.map((u) => u.id);
        const todasDoGrupo = ids.every((id) => estado.marcadas.has(id));
        const marcarGrupo = el("input", {
          type: "checkbox",
          marcado: todasDoGrupo,
          "aria-label": `Marcar todas de ${g.material}`,
        });
        marcarGrupo.addEventListener("change", () => {
          for (const id of ids) {
            if (marcarGrupo.checked) estado.marcadas.add(id);
            else estado.marcadas.delete(id);
          }
          desenharPosse();
        });
        return el(
          "div",
          { classe: "grupo-posse" },
          el(
            "div",
            { classe: "grupo-posse__cabeca" },
            el(
              "label",
              { classe: "caixa-marcar" },
              marcarGrupo,
              el("strong", {}, `${g.quantidade}× ${g.material}`),
            ),
            el(
              "span",
              { classe: "texto-3 pequeno" },
              `Retirada ${dataHora(g.retirada_em)} · por ${rotuloMilitar(g.entregue_por_posto, g.entregue_por_guerra)}`,
            ),
            el(
              "span",
              { classe: "linha-acoes" },
              g.estado_retirada === "REGULAR" ? selo("Saiu regular", "atencao") : null,
              seloPrazo(g.prazo),
            ),
          ),
          el(
            "div",
            { classe: "grupo-posse__unidades" },
            g.unidades.map((u) => {
              const caixa = el("input", { type: "checkbox", marcado: estado.marcadas.has(u.id) });
              caixa.addEventListener("change", () => {
                if (caixa.checked) estado.marcadas.add(u.id);
                else estado.marcadas.delete(u.id);
                desenharPosse();
              });
              return el(
                "label",
                { classe: "unidade-marcar" },
                caixa,
                el("span", { classe: "mono" }, `BMP ${u.bmp ?? "—"}`),
              );
            }),
          ),
          g.observacao
            ? el("p", { classe: "texto-3 pequeno" }, `Na retirada: ${g.observacao}`)
            : null,
        );
      }),
    );
    atualizar();
  }

  // ---------------------------------------------------------- estado
  const blocoEstado = el(
    "div",
    { classe: "campo", "data-campo": "estado" },
    el("span", { classe: "campo__rotulo" }, "Estado em que o material voltou"),
    segmentado({
      nome: "estado",
      rotulo: "Estado do material",
      valor: "BOM",
      opcoes: [
        { valor: "BOM", texto: "Bom", ponto: "ok" },
        { valor: "AVARIADO", texto: "Avariado (manutenção)", ponto: "atencao" },
        { valor: "INSERVIVEL", texto: "Inservível (baixa)", ponto: "perigo" },
      ],
    }),
    el(
      "span",
      { classe: "campo__ajuda" },
      "Itens em estados diferentes: devolva em duas vezes (marque só os de cada estado).",
    ),
  );
  const observacao = area({ nome: "observacao", placeholder: "Ex.: alça rompida; visor trincado" });
  const regra = el("span", { classe: "opcional" }, " (opcional)");
  const blocoObservacao = campo({ rotulo: "Observação", controle: observacao, nome: "observacao" });
  blocoObservacao.querySelector(".campo__rotulo").append(regra);
  const condicao = el("div", { classe: "passos" }, blocoEstado, blocoObservacao);
  condicao.addEventListener("change", atualizar);

  // ---------------------------------------------------------- resumo
  const resumoMilitar = el("span", {}, "—");
  const resumoQtd = el("span", {}, "—");
  const confirmarBotao = botao("Confirmar devolução", {
    classe: "primario grande largo",
    tipo: "submit",
    iconeNome: "ok",
    disabled: true,
  });
  const u = contexto.usuario;

  function atualizar() {
    const problema = valorMarcado(condicao, "estado") !== "BOM";
    regra.textContent = problema ? " (obrigatória: descreva o problema)" : " (opcional)";
    resumoMilitar.replaceChildren(
      estado.pessoa ? militar(estado.pessoa.posto, estado.pessoa.nome_guerra) : "—",
    );
    resumoQtd.textContent = estado.marcadas.size ? `${estado.marcadas.size} unidade(s)` : "—";
    confirmarBotao.disabled = !(estado.pessoa && estado.marcadas.size > 0);
  }

  const formulario = el(
    "form",
    { novalidate: true, classe: "duas-colunas duas-colunas--lateral" },
    el(
      "div",
      { classe: "passos" },
      cartao({
        titulo: "1. Quem está devolvendo",
        sub: "Militares sem material em posse aparecem desabilitados",
        corpo: el("div", { classe: "passos" }, buscaMilitar.bloco, resultados, escolhido),
      }),
      cartao({
        titulo: "2. O que está voltando",
        sub: "Marque as unidades conferidas no balcão",
        corpo: listaPosse,
      }),
      cartao({ titulo: "3. Conferência", corpo: condicao }),
    ),
    el(
      "aside",
      { classe: "resumo" },
      cartao({
        titulo: "Resumo da devolução",
        corpo: el(
          "div",
          {},
          el("div", { classe: "resumo__linha" }, el("span", {}, "Militar"), resumoMilitar),
          el("div", { classe: "resumo__linha" }, el("span", {}, "Unidades"), resumoQtd),
          el(
            "div",
            { classe: "resumo__linha" },
            el("span", {}, "Recebido por"),
            el("span", {}, `${rotuloMilitar(u.posto, u.nome_guerra)} (você)`),
          ),
          el(
            "div",
            { classe: "resumo__linha" },
            el("span", {}, "Data e hora"),
            el("span", {}, "no momento da confirmação"),
          ),
        ),
        pe: confirmarBotao,
      }),
    ),
  );

  formulario.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const estadoMaterial = valorMarcado(condicao, "estado");
    const obs = observacao.value.trim();
    if (estadoMaterial !== "BOM" && !obs) {
      avisar("Descreva o problema do material na observação.", {
        erro: true,
        titulo: "Observação obrigatória",
      });
      observacao.focus();
      return;
    }
    await comCarregamento(confirmarBotao, async () => {
      try {
        const r = await pedir("POST", "/devolucoes", {
          pessoa_id: estado.pessoa.id,
          unidades: [...estado.marcadas],
          estado: estadoMaterial,
          observacao: obs || null,
        });
        window.dispatchEvent(new Event("almox:mudou"));
        const pessoa = estado.pessoa;
        dialogo({
          titulo: "Devolução registrada",
          corpo: el(
            "div",
            { classe: "comprovante" },
            el("div", { classe: "comprovante__selo" }, icone("ok", "icone--24")),
            el(
              "div",
              { classe: "comprovante__titulo" },
              `${r.quantidade} unidade(s) recebida(s) de ${rotuloMilitar(pessoa.posto, pessoa.nome_guerra)}`,
            ),
            el("div", { classe: "comprovante__codigo mono" }, `Operação ${r.operacao}`),
            estadoMaterial !== "BOM"
              ? el(
                  "div",
                  { classe: "alerta alerta--atencao" },
                  icone("ferramenta"),
                  el(
                    "span",
                    {},
                    estadoMaterial === "AVARIADO"
                      ? "As unidades foram para manutenção."
                      : "As unidades ficaram com baixa pendente.",
                  ),
                )
              : null,
          ),
          acoes: [{ texto: "Fechar", classe: "primario" }],
        });
        observacao.value = "";
        parametros.operacao = undefined;
        await carregarPosse();
      } catch (erro) {
        tratarErro(erro, formulario);
        if (erro instanceof ErroApi && erro.status === 409) await carregarPosse();
      }
    });
  });

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Receber devolução"),
        el(
          "p",
          {},
          "Confira o material no balcão, marque o que voltou e o estado. A retirada original continua no histórico.",
        ),
      ),
      el(
        "div",
        { classe: "cabecalho-pagina__acoes" },
        el(
          "a",
          { classe: "botao botao--secundario", href: "#/posse" },
          icone("posse", "icone--16"),
          "Ver tudo em posse",
        ),
      ),
    ),
    formulario,
  );
  atualizar();

  // Veio de "Receber" na lista de posse: abre o militar (e marca só aquela retirada).
  if (parametros.pessoa) {
    try {
      const { militares } = await pedir("GET", "/militares");
      const p = militares.find((m) => String(m.id) === parametros.pessoa);
      if (p) await escolher({ ...p, em_posse: p.em_posse });
    } catch (erro) {
      tratarErro(erro);
    }
  } else {
    buscaMilitar.controle.focus();
  }
}
