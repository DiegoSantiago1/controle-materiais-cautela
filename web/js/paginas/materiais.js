// Materiais e categorias (administrador): o catálogo. Cadastro e edição de material,
// categorias e subcategorias. A entrada de unidades fica no Estoque (painel do material).

import { pedir } from "../api.js";
import { irPara, referencias, tratarErro } from "../contexto.js";
import {
  area,
  avisar,
  botao,
  campo,
  campoBusca,
  dialogo,
  dinheiro,
  duracao,
  el,
  entrada,
  icone,
  limparErros,
  normalizar,
  numero,
  selecao,
  selo,
  tabela,
  vazio,
} from "../ui.js";

const UNIDADES = ["UN", "CX", "PCT", "RESMA", "L", "GL", "KG", "M", "ROLO", "PAR", "FRASCO"];

function opcoesSubcategoria(refs) {
  return refs.categorias.map((c) => ({
    grupo: c.nome,
    opcoes: c.subcategorias.map((s) => ({ valor: s.id, texto: s.nome })),
  }));
}

const inteiroOuNulo = (v) => (v === "" || v === undefined || v === null ? null : Number(v));

/** Cadastro (m = null) ou edição de um material. */
export async function editarMaterial(m, aposMudar) {
  const refs = await referencias(true);
  const novo = !m;
  const controle = selecao({
    nome: "controle",
    opcoes: [
      { valor: "SERIAL", texto: "Patrimonial (cada unidade com BMP, cautelável)" },
      { valor: "CONSUMO", texto: "Consumo (só quantidade, não retorna)" },
    ],
    valor: m?.controle ?? "SERIAL",
  });
  if (!novo) controle.disabled = true;

  const blocoSerial = el(
    "div",
    { classe: "grade-campos grade-campos--2" },
    campo({
      rotulo: "Prazo de devolução (horas)",
      nome: "prazo_devolucao_horas",
      ajuda: "Vazio: patrimônio que não sai emprestado (ex.: armário)",
      controle: entrada({
        nome: "prazo_devolucao_horas",
        tipo: "number",
        min: 1,
        max: 8760,
        valor: m?.prazo_devolucao_horas ?? (novo ? "24" : ""),
        modo: "numeric",
      }),
    }),
  );
  const blocoConsumo = el(
    "div",
    { classe: "grade-campos grade-campos--2" },
    campo({
      rotulo: "Unidade de medida",
      nome: "unidade_medida",
      controle: selecao({
        nome: "unidade_medida",
        opcoes: UNIDADES.map((u) => ({ valor: u, texto: u })),
        valor: m?.unidade_medida ?? "UN",
      }),
    }),
    novo
      ? campo({
          rotulo: "Estoque máximo",
          nome: "estoque_maximo",
          controle: entrada({
            nome: "estoque_maximo",
            tipo: "number",
            min: 1,
            valor: "100",
            modo: "numeric",
          }),
        })
      : null,
    novo
      ? campo({
          rotulo: "Local de armazenagem",
          nome: "local_id",
          controle: selecao({
            nome: "local_id",
            opcoes: refs.locais.map((l) => ({ valor: l.id, texto: l.nome })),
            valor: refs.locais.find((l) => l.nome === "Almoxarifado de Consumo")?.id,
          }),
        })
      : null,
  );
  if (!novo) blocoConsumo.querySelector("select").disabled = true;

  const ativo = el("input", { type: "checkbox", name: "ativo", marcado: m?.ativo ?? true });
  const corpo = [
    campo({
      rotulo: "Nome",
      nome: "nome",
      controle: entrada({
        nome: "nome",
        max: 120,
        valor: m?.nome ?? "",
        placeholder: "Ex.: Escudo antitumulto de policarbonato",
      }),
    }),
    el(
      "div",
      { classe: "grade-campos grade-campos--2" },
      campo({
        rotulo: "Subcategoria",
        nome: "subcategoria_id",
        controle: selecao({
          nome: "subcategoria_id",
          opcoes: opcoesSubcategoria(refs),
          valor: m?.subcategoria_id,
          vazia: novo ? "Escolha…" : undefined,
        }),
      }),
      campo({ rotulo: "Tipo de controle", nome: "controle", controle }),
    ),
    blocoSerial,
    blocoConsumo,
    el(
      "div",
      { classe: "grade-campos grade-campos--2" },
      campo({
        rotulo: "Estoque mínimo",
        nome: "estoque_minimo",
        opcional: true,
        ajuda: "Abaixo dele o material entra em alerta",
        controle: entrada({
          nome: "estoque_minimo",
          tipo: "number",
          min: 0,
          valor: m?.estoque_minimo ?? "",
          modo: "numeric",
        }),
      }),
      campo({
        rotulo: "Valor unitário (R$, fictício)",
        nome: "custo_unitario",
        controle: entrada({
          nome: "custo_unitario",
          tipo: "number",
          min: 0,
          passo: "0.01",
          valor: m?.custo_unitario ?? "0",
          modo: "decimal",
        }),
      }),
    ),
    campo({
      rotulo: "Descrição",
      nome: "descricao",
      opcional: true,
      controle: area({ nome: "descricao", valor: m?.descricao ?? "" }),
    }),
    novo
      ? null
      : el(
          "label",
          { classe: "caixa-marcar" },
          ativo,
          "Material ativo (recebe entradas e aparece na retirada)",
        ),
  ];

  const ajustarBlocos = () => {
    const serial = controle.value === "SERIAL";
    blocoSerial.hidden = !serial;
    blocoConsumo.hidden = serial;
  };
  controle.addEventListener("change", ajustarBlocos);
  ajustarBlocos();

  dialogo({
    titulo: novo ? "Novo material" : `Editar: ${m.nome}`,
    subtitulo: novo
      ? "O código (ex.: ESC-0001) é gerado pelo sistema."
      : `${m.codigo} · o tipo de controle não muda depois do cadastro`,
    largo: true,
    corpo,
    acoes: [
      { texto: "Cancelar" },
      {
        texto: novo ? "Cadastrar material" : "Salvar alterações",
        classe: "primario",
        tipo: "submit",
        icone: "ok",
      },
    ],
    aoEnviar: async (form, { fechar }) => {
      limparErros(form);
      const d = Object.fromEntries(new FormData(form));
      const serial = (novo ? controle.value : m.controle) === "SERIAL";
      try {
        if (novo) {
          const r = await pedir("POST", "/materiais", {
            nome: d.nome,
            subcategoria_id: inteiroOuNulo(d.subcategoria_id),
            controle: controle.value,
            unidade_medida: serial ? "UN" : d.unidade_medida,
            prazo_devolucao_horas: serial ? inteiroOuNulo(d.prazo_devolucao_horas) : null,
            estoque_minimo: inteiroOuNulo(d.estoque_minimo),
            estoque_maximo: serial ? null : inteiroOuNulo(d.estoque_maximo),
            local_id: serial ? null : inteiroOuNulo(d.local_id),
            custo_unitario: Number(d.custo_unitario || 0),
            descricao: d.descricao || null,
          });
          fechar();
          avisar("Agora dê entrada nas unidades pelo Estoque.", { titulo: "Material cadastrado" });
          if (aposMudar) await aposMudar();
          else irPara("estoque", { material: r.id });
        } else {
          await pedir("PUT", `/materiais/${m.id}`, {
            nome: d.nome,
            subcategoria_id: inteiroOuNulo(d.subcategoria_id),
            prazo_devolucao_horas: serial ? inteiroOuNulo(d.prazo_devolucao_horas) : null,
            estoque_minimo: inteiroOuNulo(d.estoque_minimo),
            custo_unitario: Number(d.custo_unitario || 0),
            descricao: d.descricao || null,
            ativo: ativo.checked,
          });
          fechar();
          avisar(m.nome, { titulo: "Cadastro atualizado" });
          await aposMudar?.();
        }
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

function pedirNome({ titulo, subtitulo, valor = "", rotulo = "Nome", enviar }) {
  dialogo({
    titulo,
    subtitulo,
    corpo: campo({ rotulo, nome: "nome", controle: entrada({ nome: "nome", max: 120, valor }) }),
    acoes: [{ texto: "Cancelar" }, { texto: "Salvar", classe: "primario", tipo: "submit" }],
    aoEnviar: async (form, { fechar }) => {
      try {
        await enviar(new FormData(form).get("nome"));
        fechar();
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

export async function renderizar(alvo, parametros) {
  const [{ materiais }, refs] = await Promise.all([pedir("GET", "/estoque"), referencias(true)]);
  const aba = parametros.aba === "categorias" ? "categorias" : "materiais";
  const recarregar = () => irPara("materiais", { aba });

  const abas = el(
    "div",
    { classe: "abas", role: "tablist" },
    [
      ["materiais", "Materiais", materiais.length],
      ["categorias", "Categorias", refs.categorias.length],
    ].map(([chave, texto, n]) =>
      el(
        "button",
        {
          type: "button",
          role: "tab",
          "aria-selected": String(chave === aba),
          onclick: () => irPara("materiais", { aba: chave }),
        },
        texto,
        el("span", { classe: "contagem" }, numero(n)),
      ),
    ),
  );

  let conteudo;
  if (aba === "materiais") {
    const buscaTexto = campoBusca({ placeholder: "Nome, código, categoria" });
    const filtroCategoria = selecao({
      nome: "categoria",
      vazia: "Todas as categorias",
      opcoes: refs.categorias.map((c) => ({ valor: String(c.id), texto: c.nome })),
    });
    const corpo = el("div", {});
    const desenhar = () => {
      const termo = normalizar(buscaTexto.controle.value);
      const linhas = materiais.filter(
        (m) =>
          (!filtroCategoria.value || String(m.categoria_id) === filtroCategoria.value) &&
          (!termo ||
            normalizar(`${m.nome} ${m.codigo} ${m.categoria} ${m.subcategoria}`).includes(termo)),
      );
      corpo.replaceChildren(
        linhas.length === 0
          ? vazio({ icone: "busca", titulo: "Nenhum material" })
          : tabela({
              linhas,
              colunas: [
                {
                  titulo: "Material",
                  principal: true,
                  render: (m) =>
                    el(
                      "div",
                      { classe: "celula-principal" },
                      el("strong", {}, m.nome),
                      el("span", {}, `${m.codigo} · ${m.categoria} › ${m.subcategoria}`),
                    ),
                },
                {
                  titulo: "Tipo",
                  classe: "estreita",
                  render: (m) =>
                    m.controle === "SERIAL"
                      ? selo("Patrimonial", "info", true)
                      : selo(`Consumo · ${m.unidade_medida}`, "neutro", true),
                },
                {
                  titulo: "Prazo",
                  classe: "estreita",
                  render: (m) =>
                    m.prazo_devolucao_horas ? duracao(m.prazo_devolucao_horas * 3_600_000) : "—",
                },
                {
                  titulo: "Mínimo",
                  classe: "direita estreita",
                  render: (m) => m.estoque_minimo ?? "—",
                },
                {
                  titulo: "Valor",
                  classe: "direita estreita",
                  render: (m) => dinheiro(m.custo_unitario),
                },
                {
                  titulo: "Situação",
                  classe: "estreita",
                  render: (m) => (m.ativo ? selo("Ativo", "ok") : selo("Inativo")),
                },
                {
                  titulo: "",
                  rotulo: "",
                  classe: "direita estreita",
                  render: (m) =>
                    el(
                      "div",
                      { classe: "linha-acoes" },
                      botao("Editar", {
                        classe: "fantasma pequeno",
                        iconeNome: "editar",
                        aoClicar: () => editarMaterial(m, recarregar),
                      }),
                      el(
                        "a",
                        {
                          classe: "botao botao--fantasma botao--pequeno",
                          href: `#/estoque?material=${m.id}`,
                        },
                        icone("estoque", "icone--16"),
                        "Estoque",
                      ),
                    ),
                },
              ],
            }),
      );
    };
    buscaTexto.controle.addEventListener("input", desenhar);
    filtroCategoria.addEventListener("input", desenhar);
    desenhar();
    conteudo = [el("div", { classe: "filtros" }, buscaTexto.bloco, filtroCategoria), corpo];
  } else {
    conteudo = el(
      "div",
      { classe: "cartao__corpo" },
      el(
        "div",
        { classe: "categorias" },
        refs.categorias.map((c) =>
          el(
            "div",
            { classe: "categoria" },
            el(
              "div",
              { classe: "categoria__cabeca" },
              icone("materiais", "icone--16"),
              c.nome,
              el(
                "span",
                { classe: "texto-3 pequeno" },
                `${c.subcategorias.length} subcategoria(s)`,
              ),
              botao("Renomear", {
                classe: "fantasma pequeno",
                iconeNome: "editar",
                aoClicar: () =>
                  pedirNome({
                    titulo: "Renomear categoria",
                    valor: c.nome,
                    enviar: async (nome) => {
                      await pedir("PATCH", `/categorias/${c.id}`, { nome });
                      avisar(nome, { titulo: "Categoria renomeada" });
                      recarregar();
                    },
                  }),
              }),
              botao("Subcategoria", {
                classe: "suave pequeno",
                iconeNome: "mais",
                aoClicar: () =>
                  pedirNome({
                    titulo: "Nova subcategoria",
                    subtitulo: `Em ${c.nome}`,
                    enviar: async (nome) => {
                      await pedir("POST", "/subcategorias", { categoria_id: c.id, nome });
                      avisar(nome, { titulo: "Subcategoria criada" });
                      recarregar();
                    },
                  }),
              }),
            ),
            el(
              "div",
              { classe: "categoria__subs" },
              c.subcategorias.length === 0
                ? el("span", { classe: "texto-3 pequeno" }, "Nenhuma subcategoria ainda.")
                : c.subcategorias.map((s) =>
                    el(
                      "span",
                      { classe: "sub" },
                      s.nome,
                      botao("", {
                        classe: "fantasma icone pequeno",
                        iconeNome: "editar",
                        "aria-label": `Renomear ${s.nome}`,
                        aoClicar: () =>
                          pedirNome({
                            titulo: "Renomear subcategoria",
                            valor: s.nome,
                            enviar: async (nome) => {
                              await pedir("PATCH", `/subcategorias/${s.id}`, { nome });
                              avisar(nome, { titulo: "Subcategoria renomeada" });
                              recarregar();
                            },
                          }),
                      }),
                    ),
                  ),
            ),
          ),
        ),
      ),
    );
  }

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Materiais e categorias"),
        el("p", {}, "O catálogo do almoxarifado. Cada alteração fica registrada na auditoria."),
      ),
      el(
        "div",
        { classe: "cabecalho-pagina__acoes" },
        botao("Nova categoria", {
          classe: "secundario",
          iconeNome: "mais",
          aoClicar: () =>
            pedirNome({
              titulo: "Nova categoria",
              enviar: async (nome) => {
                await pedir("POST", "/categorias", { nome });
                avisar(nome, { titulo: "Categoria criada" });
                irPara("materiais", { aba: "categorias" });
              },
            }),
        }),
        botao("Novo material", {
          classe: "primario",
          iconeNome: "mais",
          aoClicar: () => editarMaterial(null),
        }),
      ),
    ),
    el("section", { classe: "cartao" }, abas, conteudo),
  );
}
