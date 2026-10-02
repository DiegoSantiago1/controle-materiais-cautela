/**
 * Tradução de erros para respostas HTTP.
 *
 * As regras de negócio moram nas funções do banco, que sinalizam cada motivo com um
 * SQLSTATE próprio (ALM01 a ALM13, migrações 0004 e 0015). A API não reescreve a regra: só
 * traduz o código para o status HTTP certo. As mensagens ALMxx foram escritas para
 * serem lidas por quem opera e podem ir para a tela; qualquer outro erro do banco vira
 * uma mensagem genérica (o detalhe fica só no log do servidor).
 */
import type { DatabaseError } from "pg";

export class ErroHttp extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly codigo: string,
  ) {
    super(message);
  }
}

const STATUS_POR_SQLSTATE: Record<string, { status: number; codigo: string }> = {
  ALM01: { status: 409, codigo: "ESTOQUE_INSUFICIENTE" },
  ALM02: { status: 409, codigo: "OPERACAO_INCOMPATIVEL" },
  ALM03: { status: 409, codigo: "PESSOA_FORA_DA_UNIDADE" },
  ALM04: { status: 409, codigo: "NAO_E_O_DETENTOR" },
  ALM05: { status: 403, codigo: "SEM_PERMISSAO" },
  ALM06: { status: 409, codigo: "TRANSICAO_PROIBIDA" },
  ALM07: { status: 409, codigo: "ESTORNO_INVALIDO" },
  ALM08: { status: 409, codigo: "FORA_DE_ORDEM" },
  ALM09: { status: 404, codigo: "NAO_ENCONTRADO" },
  ALM10: { status: 422, codigo: "PARAMETRO_INVALIDO" },
  ALM11: { status: 409, codigo: "DUPLICADO" },
  ALM12: { status: 409, codigo: "HISTORICO_IMUTAVEL" },
  ALM13: { status: 401, codigo: "SEM_SESSAO" },
};

// Erros de concorrência: o pedido estava certo, só precisa ser repetido.
const CONCORRENCIA = new Set(["40P01", "40001", "55P03"]);

function eErroDoBanco(erro: unknown): erro is DatabaseError {
  return erro instanceof Error && typeof (erro as DatabaseError).code === "string";
}

/** Erro do banco → ErroHttp, ou undefined se não for um erro esperado. */
export function traduzirErroDoBanco(erro: unknown): ErroHttp | undefined {
  if (!eErroDoBanco(erro) || erro.code === undefined) return undefined;
  const regra = STATUS_POR_SQLSTATE[erro.code];
  if (regra !== undefined) return new ErroHttp(regra.status, erro.message, regra.codigo);
  // FK violada: um id que não existe (por exemplo, pessoa inexistente numa retirada).
  if (erro.code === "23503") {
    return new ErroHttp(404, "Registro informado não existe.", "NAO_ENCONTRADO");
  }
  // statement_timeout ou cancelamento: o banco está sobrecarregado, não é culpa do pedido.
  if (erro.code === "57014") {
    return new ErroHttp(503, "O banco demorou a responder. Tente de novo.", "INDISPONIVEL");
  }
  // Deadlock, conflito de serialização ou trava ocupada: outro atendimento ao mesmo tempo.
  if (CONCORRENCIA.has(erro.code)) {
    return new ErroHttp(
      503,
      "Outro atendimento mexeu nos mesmos itens. Tente de novo.",
      "TENTE_DE_NOVO",
    );
  }
  // Últimas linhas de defesa do banco (as funções validam antes, com mensagem própria).
  if (erro.code === "23505") {
    return new ErroHttp(409, "Já existe um registro com esse valor.", "DUPLICADO");
  }
  if (erro.code === "23514" || erro.code === "22001") {
    return new ErroHttp(422, "Algum valor está em formato inválido.", "PARAMETRO_INVALIDO");
  }
  return undefined;
}
