// Nova retirada: quem pega (militar), o quê (um ou mais materiais, por quantidade ou pelo
// BMP) e em que estado. Quem entrega é quem está logado; data e hora são do servidor.
// Tudo vai num pedido só: o banco grava numa transação, com um código de operação.

import { consulta, ErroApi, pedir } from "../api.js";
import { contexto, irPara, tratarErro } from "../contexto.js";
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
  duracao,
  el,
  entrada,
  icone,
  militar,
  normalizar,
  rotuloMilitar,
  segmentado,
  selo,
  seloPosto,
  valorMarcado,
} from "../ui.js";

export async function renderizar(alvo) {
  const { materiais } = await pedir("GET", "/estoque");
  const estado = { pessoa: null, itens: new Map() };

  // ---------------------------------------------------------- passo 1: militar
  const passoMilitar = el("div", { classe: "passos" });
  const buscaMilitar = campoBusca({
    placeholder: "Nome de guerra, posto, nome ou matrícula",
    rotulo: "Buscar militar",
  });
  const resultadosMilitar = el("ul", {
    classe: "resultados",
    "aria-label": "Militares encontrados",
  });
  const escolhidoMilitar = el("div", { hidden: true });

  busca({
    entrada: buscaMilitar.controle,
    lista: resultadosMilitar,
    buscar: async (termo) => (await pedir("GET", `/pessoas${consulta({ busca: termo })}`)).pessoas,
    desenhar: (p) =>
      el(
        "button",
        { classe: "resultado", type: "button", onclick: () => escolherMilitar(p) },
        seloPosto(p.posto),
        el(
          "span",
          { classe: "resultado__texto" },
          el("strong", { classe: "militar__guerra" }, p.nome_guerra.toUpperCase()),
          el("span", { classe: "resultado__sub" }, `${p.nome} · ${p.setor} · mat. ${p.matricula}`),
        ),
        p.em_posse ? selo(`${p.em_posse} em posse`, "atencao") : null,
      ),
    aoErro: tratarErro,
  });

  function escolherMilitar(p) {
    estado.pessoa = p;
    escolhidoMilitar.replaceChildren(
      el(
        "div",
        { classe: "escolhido" },
        militar(p.posto, p.nome_guerra, `${p.nome} · ${p.setor} · mat. ${p.matricula}`),
        el("span", { classe: "escolhido__texto" }),
        p.em_posse ? selo(`${p.em_posse} já em posse`, "atencao") : selo("Nada em posse", "ok"),
        botao("Trocar", { classe: "fantasma pequeno", aoClicar: trocarMilitar }),
      ),
    );
    escolhidoMilitar.hidden = false;
    buscaMilitar.bloco.hidden = true;
    resultadosMilitar.replaceChildren();
    atualizar();
    buscaMaterial.controle.focus();
  }

  function trocarMilitar() {
    estado.pessoa = null;
    escolhidoMilitar.hidden = true;
    buscaMilitar.bloco.hidden = false;
    buscaMilitar.controle.value = "";
    buscaMilitar.controle.focus();
    atualizar();
  }
  passoMilitar.append(buscaMilitar.bloco, resultadosMilitar, escolhidoMilitar);

  // ---------------------------------------------------------- passo 2: materiais
  const buscaMaterial = campoBusca({
    placeholder: "Material, código ou categoria",
    rotulo: "Buscar material",
  });
  const resultadosMaterial = el("ul", {
    classe: "resultados",
    "aria-label": "Materiais encontrados",
  });
  const buscaBmp = campoBusca({
    placeholder: "BMP ou nº de série da etiqueta",
    rotulo: "Adicionar pelo BMP",
    nome: "bmp",
  });
  const resultadosBmp = el("ul", { classe: "resultados", "aria-label": "Unidades encontradas" });
  const listaItens = el("div", { classe: "itens" });

  const retiraveis = materiais.filter(
    (m) => m.ativo && (m.controle === "CONSUMO" || m.prazo_devolucao_horas),
  );

  function desenharResultadosMaterial() {
    const termo = normalizar(buscaMaterial.controle.value);
    if (termo.length < 2) {
      resultadosMaterial.replaceChildren();
      return;
    }
    const achados = retiraveis
      .filter((m) =>
        normalizar(`${m.nome} ${m.codigo} ${m.categoria} ${m.subcategoria}`).includes(termo),
      )
      .sort((a, b) => (b.disponivel > 0) - (a.disponivel > 0) || a.nome.localeCompare(b.nome))
      .slice(0, 12);
    resultadosMaterial.replaceChildren(
      ...(achados.length === 0
        ? [el("li", { classe: "resultados__nota" }, "Nenhum material retirável com esse nome.")]
        : achados.map((m) =>
            el(
              "li",
              {},
              el(
                "button",
                {
                  classe: "resultado",
                  type: "button",
                  disabled: m.disponivel === 0,
                  onclick: () => adicionar(m, 1),
                },
                el(
                  "span",
                  { classe: "marcador" },
                  icone(m.controle === "CONSUMO" ? "caixa" : "estoque"),
                ),
                el(
                  "span",
                  { classe: "resultado__texto" },
                  el("strong", {}, m.nome),
                  el("span", { classe: "resultado__sub" }, `${m.codigo} · ${m.subcategoria}`),
                ),
                m.disponivel > 0
                  ? selo(`${m.disponivel} disponível(is)`, "ok")
                  : selo("Sem estoque", "perigo"),
              ),
            ),
          )),
    );
  }
  buscaMaterial.controle.addEventListener("input", desenharResultadosMaterial);

  busca({
    entrada: buscaBmp.controle,
    lista: resultadosBmp,
    minimo: 3,
    buscar: async (termo) =>
      (await pedir("GET", `/unidades${consulta({ busca: termo })}`)).unidades,
    desenhar: (u) => {
      const livre = u.status === "DISPONIVEL";
      const jaNaLista = estado.itens.get(u.material_tipo_id)?.unidades?.some((x) => x.id === u.id);
      return el(
        "button",
        {
          classe: "resultado",
          type: "button",
          disabled: !livre || jaNaLista,
          onclick: () => adicionarUnidade(u),
        },
        el("span", { classe: "marcador" }, icone("codigo")),
        el(
          "span",
          { classe: "resultado__texto" },
          el("strong", {}, u.material),
          el(
            "span",
            { classe: "resultado__sub" },
            `BMP ${u.bmp ?? "—"}${u.numero_serie ? ` · série ${u.numero_serie}` : ""}`,
          ),
        ),
        livre
          ? selo(jaNaLista ? "Já na lista" : "Disponível", jaNaLista ? "neutro" : "ok")
          : selo(
              u.status === "CAUTELADA"
                ? `Com ${rotuloMilitar(u.detentor_posto, u.detentor_guerra)}`
                : "Indisponível",
              "atencao",
            ),
      );
    },
    aoErro: tratarErro,
  });

  function adicionar(m, quantidade) {
    const atual = estado.itens.get(m.id);
    if (atual?.unidades) {
      avisar("Este material já está na lista por BMP. Remova-o para pedir por quantidade.", {
        erro: true,
      });
      return;
    }
    const nova = Math.min((atual?.quantidade ?? 0) + quantidade, m.disponivel);
    estado.itens.set(m.id, { material: m, quantidade: nova, unidades: null });
    buscaMaterial.controle.value = "";
    resultadosMaterial.replaceChildren();
    desenharItens();
    buscaMaterial.controle.focus();
  }

  function adicionarUnidade(u) {
    const m = materiais.find((x) => x.id === u.material_tipo_id);
    if (!m) return;
    const atual = estado.itens.get(m.id);
    if (atual && !atual.unidades) {
      avisar("Este material já está na lista por quantidade. Remova-o para escolher os BMPs.", {
        erro: true,
      });
      return;
    }
    const unidades = [...(atual?.unidades ?? []), { id: u.id, bmp: u.bmp }];
    estado.itens.set(m.id, { material: m, quantidade: unidades.length, unidades });
    buscaBmp.controle.value = "";
    resultadosBmp.replaceChildren();
    desenharItens();
    buscaBmp.controle.focus();
  }

  function contador(item) {
    const max = item.material.disponivel;
    const campoNumero = el("input", {
      type: "number",
      min: 1,
      max,
      valor: item.quantidade,
      "aria-label": `Quantidade de ${item.material.nome}`,
      inputmode: "numeric",
    });
    const definir = (n) => {
      item.quantidade = Math.max(1, Math.min(max, Number.isFinite(n) ? Math.trunc(n) : 1));
      desenharItens();
    };
    campoNumero.addEventListener("change", () => definir(Number(campoNumero.value)));
    return el(
      "div",
      { classe: "contador" },
      el(
        "button",
        {
          type: "button",
          "aria-label": "Diminuir",
          disabled: item.quantidade <= 1,
          onclick: () => definir(item.quantidade - 1),
        },
        icone("menos", "icone--16"),
      ),
      campoNumero,
      el(
        "button",
        {
          type: "button",
          "aria-label": "Aumentar",
          disabled: item.quantidade >= max,
          onclick: () => definir(item.quantidade + 1),
        },
        icone("mais", "icone--16"),
      ),
    );
  }

  function desenharItens() {
    if (estado.itens.size === 0) {
      listaItens.replaceChildren(
        el(
          "p",
          { classe: "texto-3 pequeno" },
          "Nenhum material na lista. Busque pelo nome ou leia o BMP da etiqueta.",
        ),
      );
    } else {
      listaItens.replaceChildren(
        ...[...estado.itens.values()].map((item) => {
          const m = item.material;
          const sub =
            m.controle === "CONSUMO"
              ? "Consumo · não retorna"
              : `Devolver em ${duracao(m.prazo_devolucao_horas * 3_600_000)}`;
          return el(
            "div",
            { classe: "item" },
            el(
              "div",
              { classe: "celula-principal" },
              el("strong", {}, m.nome),
              el("span", {}, `${m.codigo} · ${sub} · ${m.disponivel} disponível(is)`),
              item.unidades
                ? el(
                    "div",
                    { classe: "chips" },
                    item.unidades.map((u) => el("span", { classe: "chip" }, u.bmp)),
                  )
                : null,
            ),
            el(
              "div",
              { classe: "item__acoes" },
              item.unidades
                ? selo(`${item.unidades.length} por BMP`, "info", true)
                : contador(item),
              botao("", {
                classe: "fantasma icone pequeno",
                iconeNome: "fechar",
                "aria-label": `Remover ${m.nome}`,
                aoClicar: () => {
                  estado.itens.delete(m.id);
                  desenharItens();
                },
              }),
            ),
          );
        }),
      );
    }
    atualizar();
  }

  // ---------------------------------------------------------- passo 3: condição
  const condicao = el(
    "div",
    { classe: "passos" },
    el(
      "div",
      { classe: "campo", "data-campo": "estado" },
      el("span", { classe: "campo__rotulo" }, "Estado do material na entrega"),
      segmentado({
        nome: "estado",
        rotulo: "Estado do material",
        valor: "BOM",
        opcoes: [
          { valor: "BOM", texto: "Bom", ponto: "ok" },
          { valor: "REGULAR", texto: "Regular (com marcas de uso)", ponto: "atencao" },
        ],
      }),
    ),
  );
  const observacao = area({
    nome: "observacao",
    placeholder: "Ex.: riscos na viseira; alça descosturada",
  });
  const regraObservacao = el("span", { classe: "opcional" }, " (opcional)");
  const blocoObservacao = campo({ rotulo: "Observação", controle: observacao, nome: "observacao" });
  blocoObservacao.querySelector(".campo__rotulo").append(regraObservacao);
  const finalidade = entrada({
    nome: "finalidade",
    max: 120,
    placeholder: "Ex.: serviço de dia, treino, missão",
  });
  condicao.append(
    blocoObservacao,
    campo({ rotulo: "Finalidade", opcional: true, controle: finalidade, nome: "finalidade" }),
  );
  condicao.addEventListener("change", atualizar);

  // ---------------------------------------------------------- resumo
  const resumoMilitar = el("span", {}, "—");
  const resumoItens = el("span", {}, "—");
  const confirmarBotao = botao("Confirmar retirada", {
    classe: "primario grande largo",
    tipo: "submit",
    iconeNome: "ok",
    disabled: true,
  });
  const u = contexto.usuario;
  const resumo = el(
    "aside",
    { classe: "resumo" },
    cartao({
      titulo: "Resumo da retirada",
      corpo: el(
        "div",
        {},
        el("div", { classe: "resumo__linha" }, el("span", {}, "Militar"), resumoMilitar),
        el("div", { classe: "resumo__linha" }, el("span", {}, "Itens"), resumoItens),
        el(
          "div",
          { classe: "resumo__linha" },
          el("span", {}, "Entregue por"),
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
  );

  function atualizar() {
    const regular = valorMarcado(condicao, "estado") === "REGULAR";
    regraObservacao.textContent = regular ? " (obrigatória: descreva as marcas)" : " (opcional)";
    resumoMilitar.replaceChildren(
      estado.pessoa ? militar(estado.pessoa.posto, estado.pessoa.nome_guerra) : "—",
    );
    const total = [...estado.itens.values()].reduce((s, i) => s + i.quantidade, 0);
    resumoItens.textContent = estado.itens.size
      ? `${estado.itens.size} material(is) · ${total} unidade(s)`
      : "—";
    confirmarBotao.disabled = !(estado.pessoa && estado.itens.size > 0);
    for (const [i, passo] of [estado.pessoa, estado.itens.size > 0].entries()) {
      numeros[i]?.classList.toggle("passo--feito", Boolean(passo));
    }
  }

  // ---------------------------------------------------------- montagem
  const numeros = [];
  const cabecaPasso = (n, titulo, sub) => {
    const cabeca = el(
      "div",
      { classe: "passo__cabeca" },
      el("span", { classe: "passo__numero" }, String(n)),
      el("div", {}, el("h2", {}, titulo), sub ? el("p", { classe: "cartao__sub" }, sub) : null),
    );
    numeros.push(cabeca);
    return cabeca;
  };
  const cartaoPasso = (cabeca, corpo) =>
    el(
      "section",
      { classe: "cartao" },
      el("div", { classe: "cartao__cabeca" }, cabeca),
      el("div", { classe: "cartao__corpo" }, corpo),
    );

  const formulario = el(
    "form",
    { novalidate: true, classe: "duas-colunas duas-colunas--lateral" },
    el(
      "div",
      { classe: "passos" },
      cartaoPasso(
        cabecaPasso(1, "Quem vai retirar", "O militar que recebe o material"),
        passoMilitar,
      ),
      cartaoPasso(
        cabecaPasso(
          2,
          "Materiais",
          "Por quantidade (o sistema escolhe as unidades) ou pelo BMP da etiqueta",
        ),
        el(
          "div",
          { classe: "passos" },
          el(
            "div",
            { classe: "grade-campos grade-campos--2" },
            el("div", {}, buscaMaterial.bloco, resultadosMaterial),
            el("div", {}, buscaBmp.bloco, resultadosBmp),
          ),
          listaItens,
        ),
      ),
      cartaoPasso(cabecaPasso(3, "Condição", "Registre o estado em que o material saiu"), condicao),
    ),
    resumo,
  );

  formulario.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (!estado.pessoa || estado.itens.size === 0) return;
    const estadoMaterial = valorMarcado(condicao, "estado");
    const obs = observacao.value.trim();
    if (estadoMaterial === "REGULAR" && !obs) {
      avisar("Descreva as marcas de uso na observação.", {
        erro: true,
        titulo: "Observação obrigatória",
      });
      observacao.focus();
      return;
    }
    const corpo = {
      pessoa_id: estado.pessoa.id,
      estado: estadoMaterial,
      observacao: obs || null,
      finalidade: finalidade.value.trim() || null,
      itens: [...estado.itens.values()].map((i) =>
        i.unidades
          ? { material_id: i.material.id, unidades: i.unidades.map((x) => x.id) }
          : { material_id: i.material.id, quantidade: i.quantidade },
      ),
    };
    await comCarregamento(confirmarBotao, async () => {
      try {
        const resposta = await pedir("POST", "/retiradas", corpo);
        window.dispatchEvent(new Event("almox:mudou"));
        comprovante(resposta, estado.pessoa);
        irPara("retirada"); // recarrega a página: estoque atualizado e formulário limpo
      } catch (erro) {
        tratarErro(erro, formulario);
        if (erro instanceof ErroApi && erro.status === 409) {
          const novo = await pedir("GET", "/estoque").catch(() => null);
          if (novo) {
            for (const m of novo.materiais) {
              const item = estado.itens.get(m.id);
              if (item) item.material = m;
            }
            desenharItens();
          }
        }
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
        el("h2", {}, "Nova retirada"),
        el(
          "p",
          {},
          "Entregue um ou mais materiais a um militar. Tudo é gravado de uma vez, com o mesmo código de operação.",
        ),
      ),
    ),
    formulario,
  );
  desenharItens();
  buscaMilitar.controle.focus();
}

function comprovante(resposta, pessoa) {
  const prazo = resposta.itens
    .map((i) => i.prazo)
    .filter(Boolean)
    .sort()[0];
  dialogo({
    titulo: "Retirada registrada",
    corpo: el(
      "div",
      { classe: "comprovante" },
      el("div", { classe: "comprovante__selo" }, icone("ok", "icone--24")),
      el(
        "div",
        { classe: "comprovante__titulo" },
        `Entregue a ${rotuloMilitar(pessoa.posto, pessoa.nome_guerra)}`,
      ),
      el("div", { classe: "comprovante__codigo mono" }, `Operação ${resposta.operacao}`),
      el(
        "div",
        { classe: "itens" },
        resposta.itens.map((i) =>
          el(
            "div",
            { classe: "item" },
            el(
              "div",
              { classe: "celula-principal" },
              el("strong", {}, `${i.quantidade}× ${i.material}`),
              el(
                "span",
                {},
                i.controle === "CONSUMO"
                  ? "Consumo (não retorna)"
                  : `Devolver até ${dataHora(i.prazo)}`,
              ),
              i.bmps.length
                ? el(
                    "div",
                    { classe: "chips" },
                    i.bmps.map((b) => el("span", { classe: "chip" }, b)),
                  )
                : null,
            ),
          ),
        ),
      ),
      prazo
        ? el("p", { classe: "texto-2 pequeno" }, `Primeiro prazo de devolução: ${dataHora(prazo)}.`)
        : null,
    ),
    acoes: [
      {
        texto: "Ver em posse",
        aoClicar: () => {
          document.querySelector("dialog[open]")?.close();
          irPara("posse");
        },
      },
      { texto: "Nova retirada", classe: "primario" },
    ],
  });
}
