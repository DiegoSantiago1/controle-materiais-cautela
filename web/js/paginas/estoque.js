// Estoque: por material, quantas unidades há, quantas estão disponíveis, em posse, em
// manutenção e indisponíveis, e o mínimo. O painel do material mostra cada unidade (BMP,
// situação, com quem está) e as ações de quem gere o estoque.

import { pedir } from "../api.js";
import { ADMINISTRACAO, GESTAO_DE_ESTOQUE, pode, referencias, tratarErro } from "../contexto.js";
import {
  area,
  avisar,
  botao,
  campo,
  campoBusca,
  dialogo,
  duracao,
  el,
  entrada,
  esqueleto,
  limparErros,
  normalizar,
  numero,
  painel,
  rotuloMilitar,
  SITUACOES_ESTOQUE,
  segmentado,
  selecao,
  seloEstoque,
  seloStatus,
  tabela,
  valorMarcado,
  vazio,
} from "../ui.js";
import { linhaMovimento } from "./inicio.js";
import { editarMaterial } from "./materiais.js";

const ALERTA = new Set(["ABAIXO_DO_MINIMO", "CRITICO", "SEM_ESTOQUE"]);

export async function renderizar(alvo, parametros) {
  const [{ materiais }, refs] = await Promise.all([pedir("GET", "/estoque"), referencias()]);

  const buscaTexto = campoBusca({ placeholder: "Material, código ou subcategoria" });
  buscaTexto.controle.value = parametros.busca ?? "";
  const categoria = selecao({
    nome: "categoria",
    vazia: "Todas as categorias",
    opcoes: refs.categorias.map((c) => ({ valor: String(c.id), texto: c.nome })),
    valor: parametros.categoria ?? "",
  });
  const situacao = selecao({
    nome: "situacao",
    vazia: "Todas as situações",
    valor: parametros.situacao ?? "",
    opcoes: [
      { valor: "alerta", texto: "Em alerta (abaixo do mínimo ou zerado)" },
      ...Object.entries(SITUACOES_ESTOQUE).map(([valor, [texto]]) => ({ valor, texto })),
    ],
  });
  const controle = selecao({
    nome: "controle",
    vazia: "Patrimonial e consumo",
    opcoes: [
      { valor: "SERIAL", texto: "Patrimonial (com BMP)" },
      { valor: "CONSUMO", texto: "Consumo" },
    ],
  });
  const inativos = el("input", { type: "checkbox" });
  const total = el("span", { classe: "filtros__total" });
  const corpo = el("div", {});

  function desenhar() {
    const termo = normalizar(buscaTexto.controle.value);
    const linhas = materiais.filter((m) => {
      if (!inativos.checked && !m.ativo) return false;
      if (categoria.value && String(m.categoria_id) !== categoria.value) return false;
      if (controle.value && m.controle !== controle.value) return false;
      if (situacao.value === "alerta" && !ALERTA.has(m.situacao)) return false;
      if (situacao.value && situacao.value !== "alerta" && m.situacao !== situacao.value)
        return false;
      return (
        !termo ||
        normalizar(`${m.nome} ${m.codigo} ${m.subcategoria} ${m.categoria}`).includes(termo)
      );
    });
    total.textContent = `${numero(linhas.length)} material(is)`;
    corpo.replaceChildren(
      linhas.length === 0
        ? vazio({ icone: "busca", titulo: "Nenhum material com esses filtros" })
        : tabela({
            linhas,
            aoClicar: (m) => abrirMaterial(m.id),
            rotuloLinha: (m) => `Detalhes de ${m.nome}`,
            classeLinha: (m) => (ALERTA.has(m.situacao) && m.ativo ? "linha--alerta" : ""),
            colunas: [
              {
                titulo: "Material",
                principal: true,
                render: (m) =>
                  el(
                    "div",
                    { classe: "celula-principal" },
                    el(
                      "strong",
                      {},
                      m.nome,
                      m.ativo ? null : el("span", { classe: "texto-3" }, " (inativo)"),
                    ),
                    el(
                      "span",
                      {},
                      `${m.codigo} · ${m.subcategoria}${m.controle === "CONSUMO" ? ` · ${m.unidade_medida}` : ""}`,
                    ),
                  ),
              },
              {
                titulo: "Total",
                classe: "direita estreita",
                render: (m) => numeroOuTraco(m.total),
              },
              {
                titulo: "Disponível",
                classe: "direita estreita",
                render: (m) =>
                  el(
                    "span",
                    { classe: `valor-destaque${m.disponivel === 0 ? " valor-zero" : ""}` },
                    numero(m.disponivel),
                  ),
              },
              {
                titulo: "Em posse",
                classe: "direita estreita",
                render: (m) => (m.controle === "CONSUMO" ? "—" : numeroOuTraco(m.em_posse)),
              },
              {
                titulo: "Manutenção",
                classe: "direita estreita",
                render: (m) => (m.controle === "CONSUMO" ? "—" : numeroOuTraco(m.em_manutencao)),
              },
              {
                titulo: "Indisponível",
                classe: "direita estreita",
                render: (m) => (m.controle === "CONSUMO" ? "—" : numeroOuTraco(m.indisponivel)),
              },
              {
                titulo: "Mínimo",
                classe: "direita estreita",
                render: (m) => m.estoque_minimo ?? "—",
              },
              { titulo: "Situação", classe: "estreita", render: (m) => seloEstoque(m.situacao) },
            ],
          }),
    );
  }

  async function recarregarDados() {
    const novo = await pedir("GET", "/estoque");
    materiais.splice(0, materiais.length, ...novo.materiais);
    desenhar();
  }

  async function abrirMaterial(id) {
    const { corpo: miolo } = painel({ titulo: "Material", subtitulo: "Carregando…" });
    miolo.replaceChildren(esqueleto(8));
    try {
      const detalhe = await pedir("GET", `/estoque/${id}`);
      const p = desenharPainel(detalhe, async () => {
        await recarregarDados();
        window.dispatchEvent(new Event("almox:mudou"));
        await abrirMaterial(id);
      });
      const cabecalho = document.querySelector(".painel__cabeca");
      cabecalho.querySelector("h2").textContent = detalhe.material.nome;
      const sub = cabecalho.querySelector("p");
      if (sub)
        sub.textContent = `${detalhe.material.codigo} · ${detalhe.material.categoria} › ${detalhe.material.subcategoria}`;
      miolo.replaceChildren(...p);
    } catch (erro) {
      miolo.replaceChildren(
        vazio({ icone: "alerta", titulo: "Não foi possível carregar o material" }),
      );
      tratarErro(erro);
    }
  }

  for (const c of [buscaTexto.controle, categoria, situacao, controle, inativos]) {
    c.addEventListener("input", desenhar);
  }

  const emAlerta = materiais.filter((m) => m.ativo && ALERTA.has(m.situacao)).length;
  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Estoque"),
        el(
          "p",
          {},
          `${numero(materiais.filter((m) => m.ativo).length)} materiais ativos · ${numero(emAlerta)} em alerta. As quantidades mudam sozinhas a cada retirada e devolução.`,
        ),
      ),
      pode(ADMINISTRACAO)
        ? el(
            "div",
            { classe: "cabecalho-pagina__acoes" },
            el(
              "a",
              { classe: "botao botao--secundario", href: "#/materiais" },
              "Gerenciar materiais",
            ),
          )
        : null,
    ),
    el(
      "section",
      { classe: "cartao" },
      el(
        "div",
        { classe: "filtros" },
        buscaTexto.bloco,
        categoria,
        situacao,
        controle,
        el("label", { classe: "caixa-marcar pequeno" }, inativos, "Mostrar inativos"),
        total,
      ),
      corpo,
    ),
  );
  desenhar();
  if (parametros.material) abrirMaterial(Number(parametros.material));
}

const numeroOuTraco = (n) => (n ? numero(n) : el("span", { classe: "valor-zero" }, "0"));

// ------------------------------------------------------------ painel do material
function desenharPainel({ material: m, unidades, movimentos }, aposMudar) {
  const gestao = pode(GESTAO_DE_ESTOQUE);
  const numeros = el(
    "dl",
    { classe: "numeros" },
    [
      ["Total", m.total],
      ["Disponível", m.disponivel],
      ...(m.controle === "SERIAL"
        ? [
            ["Em posse", m.em_posse],
            ["Manutenção", m.em_manutencao],
            ["Indisponível", m.indisponivel],
          ]
        : []),
      ["Mínimo", m.estoque_minimo ?? "—"],
    ].map(([rotulo, valor]) =>
      el(
        "div",
        {},
        el("dt", {}, rotulo),
        el("dd", {}, typeof valor === "number" ? numero(valor) : valor),
      ),
    ),
  );
  const detalhes = el(
    "dl",
    { classe: "detalhes" },
    el("dt", {}, "Situação"),
    el("dd", {}, seloEstoque(m.situacao)),
    el("dt", {}, "Controle"),
    el(
      "dd",
      {},
      m.controle === "SERIAL"
        ? "Patrimonial (cada unidade com BMP)"
        : `Consumo (${m.unidade_medida})`,
    ),
    el("dt", {}, "Prazo de devolução"),
    el(
      "dd",
      {},
      m.prazo_devolucao_horas
        ? duracao(m.prazo_devolucao_horas * 3_600_000)
        : m.controle === "SERIAL"
          ? "Não é cautelável"
          : "Não retorna",
    ),
    m.local ? [el("dt", {}, "Local"), el("dd", {}, m.local)] : null,
    m.descricao ? [el("dt", {}, "Descrição"), el("dd", {}, m.descricao)] : null,
  );
  const acoes = el(
    "div",
    { classe: "linha-acoes" },
    gestao
      ? botao("Dar entrada", {
          classe: "primario pequeno",
          iconeNome: "pacote-mais",
          aoClicar: () => darEntrada(m, aposMudar),
          disabled: !m.ativo,
        })
      : null,
    gestao && m.controle === "CONSUMO"
      ? botao("Ajustar inventário", {
          classe: "secundario pequeno",
          iconeNome: "editar",
          aoClicar: () => ajustar(m, aposMudar),
        })
      : null,
    pode(ADMINISTRACAO)
      ? botao("Editar cadastro", {
          classe: "secundario pequeno",
          iconeNome: "editar",
          aoClicar: () => editarMaterial(m, aposMudar),
        })
      : null,
  );

  const listaUnidades =
    m.controle === "SERIAL"
      ? [
          el("div", { classe: "secao-titulo" }, `Unidades (${numero(unidades.length)})`),
          unidades.length === 0
            ? vazio({
                icone: "caixa",
                titulo: "Nenhuma unidade cadastrada",
                texto: gestao ? "Use “Dar entrada” para incorporar unidades." : undefined,
              })
            : el(
                "div",
                { classe: "cartao" },
                tabela({
                  linhas: unidades,
                  colunas: [
                    {
                      titulo: "BMP",
                      principal: true,
                      render: (u) => el("span", { classe: "mono" }, u.bmp ?? "sem BMP"),
                    },
                    { titulo: "Situação", render: (u) => seloStatus(u.status) },
                    {
                      titulo: "Com quem / local",
                      render: (u) =>
                        u.pessoa_id ? rotuloMilitar(u.posto, u.nome_guerra) : u.local,
                    },
                    {
                      titulo: "",
                      rotulo: "",
                      classe: "direita estreita",
                      render: (u) =>
                        gestao && u.status !== "BAIXADA" && u.status !== "CAUTELADA"
                          ? botao("Situação", {
                              classe: "fantasma pequeno",
                              iconeNome: "ferramenta",
                              aoClicar: () => mudarSituacao(m, u, aposMudar),
                            })
                          : null,
                    },
                  ],
                }),
              ),
        ]
      : [];

  return [
    numeros,
    acoes.childElementCount ? acoes : null,
    detalhes,
    ...listaUnidades,
    el("div", { classe: "secao-titulo" }, "Últimos movimentos"),
    movimentos.length
      ? el(
          "div",
          { classe: "cartao" },
          el("div", { classe: "lista" }, movimentos.map(linhaMovimento)),
        )
      : vazio({ icone: "historico", titulo: "Sem movimentos" }),
  ].filter(Boolean);
}

async function darEntrada(m, aposMudar) {
  const refs = await referencias();
  const serial = m.controle === "SERIAL";
  const corpo = el(
    "div",
    { classe: "grade-campos grade-campos--2" },
    campo({
      rotulo: serial ? "Quantidade de unidades" : `Quantidade (${m.unidade_medida})`,
      nome: "quantidade",
      controle: entrada({
        nome: "quantidade",
        tipo: "number",
        min: 1,
        max: serial ? 500 : 100000,
        valor: "1",
        modo: "numeric",
      }),
    }),
    serial
      ? campo({
          rotulo: "Local de armazenagem",
          nome: "local_id",
          controle: selecao({
            nome: "local_id",
            opcoes: refs.locais.map((l) => ({ valor: l.id, texto: l.nome })),
            valor: refs.locais.find((l) => l.nome === "Reserva de Equipamentos")?.id,
          }),
        })
      : null,
    campo({
      rotulo: "Documento",
      opcional: true,
      nome: "documento",
      ajuda: "Nota fiscal, guia ou ofício",
      controle: entrada({ nome: "documento", max: 40, placeholder: "Ex.: NF 4521" }),
    }),
  );
  const estadoBloco = serial
    ? el(
        "div",
        { classe: "campo", "data-campo": "estado" },
        el("span", { classe: "campo__rotulo" }, "Estado na chegada"),
        segmentado({
          nome: "estado",
          rotulo: "Estado na chegada",
          valor: "BOM",
          opcoes: [
            { valor: "BOM", texto: "Bom", ponto: "ok" },
            { valor: "AVARIADO", texto: "Avariado", ponto: "atencao" },
            { valor: "INSERVIVEL", texto: "Inservível", ponto: "perigo" },
          ],
        }),
      )
    : null;
  const obs = campo({
    rotulo: "Observação",
    opcional: true,
    nome: "observacao",
    controle: area({ nome: "observacao" }),
  });
  dialogo({
    titulo: `Entrada: ${m.nome}`,
    subtitulo: serial
      ? "Cada unidade recebe um BMP sequencial."
      : "A quantidade é somada ao saldo.",
    corpo: [corpo, estadoBloco, obs],
    acoes: [
      { texto: "Cancelar" },
      { texto: "Registrar entrada", classe: "primario", tipo: "submit", icone: "ok" },
    ],
    aoEnviar: async (form, { fechar }) => {
      limparErros(form);
      const dados = Object.fromEntries(new FormData(form));
      try {
        const r = await pedir("POST", `/materiais/${m.id}/entradas`, {
          quantidade: Number(dados.quantidade),
          local_id: serial ? Number(dados.local_id) : undefined,
          estado: serial ? valorMarcado(form, "estado") : undefined,
          documento: dados.documento || null,
          observacao: dados.observacao || null,
        });
        fechar();
        avisar(
          serial
            ? `BMP ${r.bmps[0]} a ${r.bmps.at(-1)}.`
            : `${numero(r.quantidade)} ${m.unidade_medida} somadas ao saldo.`,
          { titulo: "Entrada registrada" },
        );
        await aposMudar();
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

async function ajustar(m, aposMudar) {
  dialogo({
    titulo: `Ajuste de inventário: ${m.nome}`,
    subtitulo: `Saldo no sistema: ${numero(m.disponivel)} ${m.unidade_medida}. Informe o que foi CONTADO; a diferença vira um ajuste no histórico.`,
    corpo: [
      campo({
        rotulo: "Quantidade contada",
        nome: "quantidade_contada",
        controle: entrada({
          nome: "quantidade_contada",
          tipo: "number",
          min: 0,
          valor: String(m.disponivel),
          modo: "numeric",
        }),
      }),
      campo({
        rotulo: "Justificativa",
        nome: "justificativa",
        controle: area({
          nome: "justificativa",
          placeholder: "Ex.: inventário mensal; pacote danificado",
        }),
      }),
    ],
    acoes: [
      { texto: "Cancelar" },
      { texto: "Registrar ajuste", classe: "primario", tipo: "submit" },
    ],
    aoEnviar: async (form, { fechar }) => {
      const dados = Object.fromEntries(new FormData(form));
      try {
        const r = await pedir("POST", `/materiais/${m.id}/ajuste`, {
          quantidade_contada: Number(dados.quantidade_contada),
          justificativa: dados.justificativa,
        });
        fechar();
        avisar(r.ajustado ? "Saldo ajustado." : "A contagem bateu com o sistema: nada a ajustar.", {
          titulo: "Inventário",
        });
        await aposMudar();
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

const TRANSICOES = {
  DISPONIVEL: ["EM_MANUTENCAO", "NAO_LOCALIZADA", "BAIXA_PENDENTE"],
  EM_MANUTENCAO: ["DISPONIVEL", "BAIXA_PENDENTE"],
  NAO_LOCALIZADA: ["DISPONIVEL", "BAIXA_PENDENTE"],
  BAIXA_PENDENTE: ["DISPONIVEL", "BAIXADA"],
  AGUARDANDO_TOMBAMENTO: ["DISPONIVEL"],
};
const NOMES = {
  DISPONIVEL: "Disponível (volta ao uso)",
  EM_MANUTENCAO: "Em manutenção",
  NAO_LOCALIZADA: "Não localizada",
  BAIXA_PENDENTE: "Baixa pendente",
  BAIXADA: "Baixada (só administrador)",
};

function mudarSituacao(m, u, aposMudar) {
  const opcoes = (TRANSICOES[u.status] ?? []).filter((s) => s !== "BAIXADA" || pode(ADMINISTRACAO));
  if (opcoes.length === 0) {
    avisar("Esta unidade não tem mudança de situação disponível para o seu perfil.", {
      erro: true,
    });
    return;
  }
  dialogo({
    titulo: `BMP ${u.bmp ?? "sem BMP"}`,
    subtitulo: `${m.nome} · hoje: ${u.status.replaceAll("_", " ").toLowerCase()}`,
    corpo: [
      campo({
        rotulo: "Nova situação",
        nome: "status",
        controle: selecao({
          nome: "status",
          opcoes: opcoes.map((s) => ({ valor: s, texto: NOMES[s] })),
        }),
      }),
      u.status === "AGUARDANDO_TOMBAMENTO"
        ? campo({
            rotulo: "BMP do tombamento",
            nome: "bmp",
            controle: entrada({ nome: "bmp", max: 7, modo: "numeric" }),
          })
        : null,
      campo({
        rotulo: "Justificativa",
        nome: "justificativa",
        controle: area({
          nome: "justificativa",
          placeholder: "Ex.: enviado à oficina; reparo concluído; laudo de inservível",
        }),
      }),
    ],
    acoes: [{ texto: "Cancelar" }, { texto: "Salvar", classe: "primario", tipo: "submit" }],
    aoEnviar: async (form, { fechar }) => {
      const dados = Object.fromEntries(new FormData(form));
      try {
        await pedir("POST", `/unidades/${u.id}/situacao`, {
          status: dados.status,
          justificativa: dados.justificativa,
          bmp: dados.bmp || null,
        });
        fechar();
        avisar(`BMP ${u.bmp ?? ""}: ${NOMES[dados.status].toLowerCase()}.`, {
          titulo: "Situação alterada",
        });
        await aposMudar();
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}
