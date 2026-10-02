// Auditoria (administrador): as alterações de cadastro feitas pela aplicação, com o antes e
// o depois. O histórico do estoque fica no Histórico; aqui ficam os cadastros e acessos.

import { pedir } from "../api.js";
import {
  campoBusca,
  dataHora,
  el,
  normalizar,
  rotuloMilitar,
  selecao,
  selo,
  tabela,
  vazio,
} from "../ui.js";

const ACOES = {
  CADASTRAR: ["Cadastro", "ok"],
  ATUALIZAR: ["Alteração", "info"],
  RENOMEAR: ["Renomeação", "info"],
  ALTERAR: ["Acesso alterado", "atencao"],
  REGISTRAR_SAIDA: ["Saída da unidade", "atencao"],
  DEFINIR_SENHA: ["Senha definida", "neutro"],
  TROCAR_SENHA: ["Troca da própria senha", "neutro"],
};
const ENTIDADES = {
  MATERIAL: "Material",
  CATEGORIA: "Categoria",
  SUBCATEGORIA: "Subcategoria",
  PESSOA: "Militar",
  USUARIO: "Usuário",
};

function detalhe(registro) {
  const d = registro.detalhe ?? {};
  const partes = Object.entries(d).map(([chave, valor]) => {
    if (valor && typeof valor === "object" && "antes" in valor) {
      return `${chave.replaceAll("_", " ")}: ${valor.antes ?? "—"} → ${valor.depois ?? "—"}`;
    }
    return `${chave.replaceAll("_", " ")}: ${valor ?? "—"}`;
  });
  return partes.length ? partes.join(" · ") : "—";
}

export async function renderizar(alvo) {
  const { registros } = await pedir("GET", "/auditoria");
  const buscaTexto = campoBusca({ placeholder: "Quem, o quê, alvo" });
  const entidade = selecao({
    nome: "entidade",
    vazia: "Tudo",
    opcoes: Object.entries(ENTIDADES).map(([valor, texto]) => ({ valor, texto })),
  });
  const corpo = el("div", {});

  function desenhar() {
    const termo = normalizar(buscaTexto.controle.value);
    const linhas = registros.filter(
      (r) =>
        (!entidade.value || r.entidade === entidade.value) &&
        (!termo ||
          normalizar(`${r.acao} ${r.alvo} ${r.executor_guerra} ${detalhe(r)}`).includes(termo)),
    );
    corpo.replaceChildren(
      linhas.length === 0
        ? vazio({
            icone: "auditoria",
            titulo: "Nenhum registro",
            texto: "As alterações de cadastro aparecem aqui.",
          })
        : tabela({
            linhas,
            colunas: [
              {
                titulo: "Quando",
                classe: "estreita",
                principal: true,
                render: (r) => dataHora(r.ocorrida_em),
              },
              {
                titulo: "O quê",
                render: (r) => {
                  const [texto, tipo] = ACOES[r.acao] ?? [r.acao, "neutro"];
                  return el(
                    "div",
                    { classe: "celula-principal" },
                    selo(texto, tipo, true),
                    el(
                      "span",
                      {},
                      `${ENTIDADES[r.entidade] ?? r.entidade}: ${r.alvo ?? `#${r.entidade_id}`}`,
                    ),
                  );
                },
              },
              {
                titulo: "Detalhe",
                render: (r) => el("span", { classe: "pequeno texto-2" }, detalhe(r)),
              },
              {
                titulo: "Quem fez",
                classe: "estreita",
                render: (r) => rotuloMilitar(r.executor_posto, r.executor_guerra),
              },
            ],
          }),
    );
  }
  buscaTexto.controle.addEventListener("input", desenhar);
  entidade.addEventListener("input", desenhar);

  alvo.replaceChildren(
    el(
      "div",
      { classe: "cabecalho-pagina" },
      el(
        "div",
        { classe: "cabecalho-pagina__texto" },
        el("h2", {}, "Auditoria"),
        el(
          "p",
          {},
          "Os 200 registros mais recentes. A tabela só aceita inclusão: nada aqui pode ser alterado ou apagado.",
        ),
      ),
    ),
    el(
      "section",
      { classe: "cartao" },
      el("div", { classe: "filtros" }, buscaTexto.bloco, entidade),
      corpo,
    ),
  );
  desenhar();
}
