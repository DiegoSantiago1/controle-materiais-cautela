// Militares (administrador): o efetivo, identificado por posto e nome de guerra.
// Cadastro, edição e saída da unidade (recusada se ainda houver material em posse).

import { pedir } from "../api.js";
import { irPara, referencias, tratarErro } from "../contexto.js";
import {
  avisar,
  botao,
  campo,
  campoBusca,
  data,
  dialogo,
  el,
  entrada,
  hojeIso,
  limparErros,
  militar,
  normalizar,
  numero,
  selecao,
  selo,
  seloPerfil,
  tabela,
  vazio,
} from "../ui.js";

async function formularioMilitar(p) {
  const refs = await referencias();
  const novo = !p;
  const corpo = [
    el(
      "div",
      { classe: "grade-campos grade-campos--2" },
      campo({
        rotulo: "Posto/graduação",
        nome: "posto",
        controle: selecao({
          nome: "posto",
          opcoes: refs.postos.map((x) => ({ valor: x.sigla, texto: `${x.sigla} · ${x.nome}` })),
          valor: p?.posto ?? "S2",
        }),
      }),
      campo({
        rotulo: "Nome de guerra",
        nome: "nome_guerra",
        ajuda: "Único entre quem está na unidade",
        controle: entrada({
          nome: "nome_guerra",
          max: 30,
          valor: p?.nome_guerra ?? "",
          placeholder: "Ex.: Souza",
        }),
      }),
    ),
    campo({
      rotulo: "Nome completo",
      nome: "nome",
      controle: entrada({ nome: "nome", max: 120, valor: p?.nome ?? "" }),
    }),
    el(
      "div",
      { classe: "grade-campos grade-campos--2" },
      campo({
        rotulo: "Setor",
        nome: "setor_id",
        controle: selecao({
          nome: "setor_id",
          opcoes: refs.setores.map((s) => ({ valor: s.id, texto: `${s.sigla} · ${s.nome}` })),
          valor: p?.setor_id,
        }),
      }),
      novo
        ? campo({
            rotulo: "Matrícula",
            nome: "matricula",
            ajuda: "7 dígitos",
            controle: entrada({
              nome: "matricula",
              max: 7,
              modo: "numeric",
              placeholder: "0000000",
            }),
          })
        : null,
      novo
        ? campo({
            rotulo: "Apresentação na unidade",
            nome: "data_entrada",
            controle: entrada({
              nome: "data_entrada",
              tipo: "date",
              valor: hojeIso(),
              max: hojeIso(),
            }),
          })
        : null,
    ),
  ];
  dialogo({
    titulo: novo ? "Novo militar" : `Editar ${p.posto} ${p.nome_guerra.toUpperCase()}`,
    subtitulo: novo ? undefined : `Matrícula ${p.matricula}`,
    largo: true,
    corpo,
    acoes: [
      { texto: "Cancelar" },
      { texto: novo ? "Cadastrar" : "Salvar", classe: "primario", tipo: "submit", icone: "ok" },
    ],
    aoEnviar: async (form, { fechar }) => {
      limparErros(form);
      const d = Object.fromEntries(new FormData(form));
      try {
        if (novo) {
          await pedir("POST", "/militares", {
            matricula: d.matricula,
            nome: d.nome,
            nome_guerra: d.nome_guerra,
            posto: d.posto,
            setor_id: Number(d.setor_id),
            data_entrada: d.data_entrada || null,
          });
        } else {
          await pedir("PUT", `/militares/${p.id}`, {
            nome: d.nome,
            nome_guerra: d.nome_guerra,
            posto: d.posto,
            setor_id: Number(d.setor_id),
          });
        }
        fechar();
        avisar(`${d.posto} ${String(d.nome_guerra).toUpperCase()}`, {
          titulo: novo ? "Militar cadastrado" : "Cadastro atualizado",
        });
        irPara("militares");
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

function registrarSaida(p) {
  dialogo({
    titulo: `Saída de ${p.posto} ${p.nome_guerra.toUpperCase()}`,
    subtitulo:
      "Transferência, licenciamento ou reserva. O usuário do sistema (se houver) é desativado.",
    corpo: [
      p.em_posse
        ? el(
            "div",
            { classe: "alerta alerta--atencao" },
            `Este militar tem ${p.em_posse} unidade(s) em posse. Receba a devolução antes: o sistema recusa a saída.`,
          )
        : null,
      campo({
        rotulo: "Data da saída",
        nome: "data_saida",
        controle: entrada({ nome: "data_saida", tipo: "date", valor: hojeIso() }),
      }),
    ],
    acoes: [{ texto: "Cancelar" }, { texto: "Registrar saída", classe: "perigo", tipo: "submit" }],
    aoEnviar: async (form, { fechar }) => {
      const d = Object.fromEntries(new FormData(form));
      try {
        await pedir("POST", `/militares/${p.id}/saida`, { data_saida: d.data_saida });
        fechar();
        avisar(`${p.posto} ${p.nome_guerra.toUpperCase()} saiu da unidade.`, {
          titulo: "Saída registrada",
        });
        irPara("militares");
      } catch (erro) {
        tratarErro(erro, form);
      }
    },
  });
}

export async function renderizar(alvo) {
  const [{ militares }, refs] = await Promise.all([pedir("GET", "/militares"), referencias()]);
  const buscaTexto = campoBusca({ placeholder: "Nome de guerra, nome, matrícula" });
  const filtroSituacao = selecao({
    nome: "situacao",
    valor: "ativos",
    opcoes: [
      { valor: "ativos", texto: "Na unidade" },
      { valor: "saiu", texto: "Já saíram" },
      { valor: "", texto: "Todos" },
    ],
  });
  const filtroSetor = selecao({
    nome: "setor",
    vazia: "Todos os setores",
    opcoes: refs.setores.map((s) => ({ valor: s.sigla, texto: s.sigla })),
  });
  const filtroPosto = selecao({
    nome: "posto",
    vazia: "Todos os postos",
    opcoes: refs.postos.map((p) => ({ valor: p.sigla, texto: p.sigla })),
  });
  const total = el("span", { classe: "filtros__total" });
  const corpo = el("div", {});

  function desenhar() {
    const termo = normalizar(buscaTexto.controle.value);
    const linhas = militares.filter((p) => {
      if (filtroSituacao.value === "ativos" && !p.na_unidade) return false;
      if (filtroSituacao.value === "saiu" && p.na_unidade) return false;
      if (filtroSetor.value && p.setor !== filtroSetor.value) return false;
      if (filtroPosto.value && p.posto !== filtroPosto.value) return false;
      return (
        !termo ||
        normalizar(
          `${p.posto} ${p.nome_guerra} ${p.nome} ${p.matricula} ${p.login ?? ""}`,
        ).includes(termo)
      );
    });
    total.textContent = `${numero(linhas.length)} militar(es)`;
    corpo.replaceChildren(
      linhas.length === 0
        ? vazio({ icone: "militares", titulo: "Nenhum militar com esses filtros" })
        : tabela({
            linhas,
            colunas: [
              {
                titulo: "Militar",
                principal: true,
                render: (p) => militar(p.posto, p.nome_guerra, p.nome),
              },
              {
                titulo: "Matrícula",
                classe: "estreita",
                render: (p) => el("span", { classe: "mono" }, p.matricula),
              },
              { titulo: "Setor", classe: "estreita", render: (p) => p.setor },
              {
                titulo: "Situação",
                classe: "estreita",
                render: (p) =>
                  p.na_unidade ? selo("Na unidade", "ok") : selo(`Saiu em ${data(p.data_saida)}`),
              },
              {
                titulo: "Usuário",
                classe: "estreita",
                render: (p) =>
                  p.login
                    ? el(
                        "div",
                        { classe: "celula-principal" },
                        el("span", { classe: "mono" }, p.login),
                        seloPerfil(p.perfil),
                      )
                    : el("span", { classe: "texto-3" }, "—"),
              },
              {
                titulo: "Em posse",
                classe: "direita estreita",
                render: (p) =>
                  p.em_posse
                    ? el(
                        "a",
                        {
                          href: `#/posse?busca=${encodeURIComponent(`${p.posto} ${p.nome_guerra}`)}`,
                        },
                        `${p.em_posse} un.`,
                      )
                    : el("span", { classe: "texto-3" }, "0"),
              },
              {
                titulo: "",
                rotulo: "",
                classe: "direita estreita",
                render: (p) =>
                  el(
                    "div",
                    { classe: "linha-acoes" },
                    botao("Editar", {
                      classe: "fantasma pequeno",
                      iconeNome: "editar",
                      aoClicar: () => formularioMilitar(p),
                    }),
                    p.na_unidade
                      ? botao("Saída", {
                          classe: "fantasma pequeno",
                          iconeNome: "saida",
                          aoClicar: () => registrarSaida(p),
                        })
                      : null,
                  ),
              },
            ],
          }),
    );
  }
  for (const c of [buscaTexto.controle, filtroSituacao, filtroSetor, filtroPosto])
    c.addEventListener("input", desenhar);

  const naUnidade = militares.filter((p) => p.na_unidade).length;
  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Militares"),
        el(
          "p",
          {},
          `${numero(naUnidade)} na unidade. O nome de guerra é como cada um é encontrado no balcão.`,
        ),
      ),
      el(
        "div",
        { classe: "cabecalho-pagina__acoes" },
        botao("Novo militar", {
          classe: "primario",
          iconeNome: "pessoa-mais",
          aoClicar: () => formularioMilitar(null),
        }),
      ),
    ),
    el(
      "section",
      { classe: "cartao" },
      el(
        "div",
        { classe: "filtros" },
        buscaTexto.bloco,
        filtroSituacao,
        filtroPosto,
        filtroSetor,
        total,
      ),
      corpo,
    ),
  );
  desenhar();
}
