// Comunicação com a API. O cookie de sessão é HttpOnly: esta página nunca o vê; o
// navegador o envia sozinho em cada pedido para o mesmo servidor.

export class ErroApi extends Error {
  constructor(status, mensagem, codigo, campo) {
    super(mensagem);
    this.status = status;
    this.codigo = codigo;
    this.campo = campo;
  }
}

export async function pedir(metodo, caminho, corpo) {
  let resposta;
  try {
    resposta = await fetch(`/api${caminho}`, {
      method: metodo,
      credentials: "same-origin",
      headers: corpo === undefined ? {} : { "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    throw new ErroApi(
      0,
      "Sem conexão com o servidor. Verifique a rede e tente de novo.",
      "SEM_CONEXAO",
    );
  }
  if (resposta.status === 204) return null;
  let dados = {};
  try {
    dados = await resposta.json();
  } catch {
    // corpo vazio ou não JSON: fica o objeto vazio
  }
  if (!resposta.ok) {
    throw new ErroApi(
      resposta.status,
      dados.erro ?? "Algo deu errado. Tente de novo.",
      dados.codigo,
      dados.campo,
    );
  }
  return dados;
}

/** Monta a query string sem os valores vazios. */
export function consulta(parametros) {
  const busca = new URLSearchParams(
    Object.entries(parametros).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  ).toString();
  return busca ? `?${busca}` : "";
}
