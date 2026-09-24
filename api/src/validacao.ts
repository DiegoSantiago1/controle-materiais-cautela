/**
 * Validação na borda: o formato do pedido é conferido aqui, antes de chegar ao banco.
 * A regra de negócio (a unidade está disponível? a pessoa está na unidade?) continua no
 * banco. Aqui só se garante que cada campo tem o tipo e o tamanho certos, para que um
 * pedido malformado receba 400 com o nome do campo, e não um erro 500 do driver.
 */
import { ErroHttp } from "./erros.ts";

export class ErroDeValidacao extends ErroHttp {
  constructor(
    readonly campo: string,
    mensagem: string,
  ) {
    super(400, mensagem, "PEDIDO_INVALIDO");
  }
}

const INT_MAX = 2_147_483_647; // maior valor de uma coluna integer do PostgreSQL

/** Id numérico de verdade (1 é aceito, "1", 1.5, -1, 1e20 e true não são). */
export function id(valor: unknown, campo: string): number {
  if (typeof valor !== "number" || !Number.isInteger(valor) || valor < 1 || valor > INT_MAX) {
    throw new ErroDeValidacao(campo, `${campo} deve ser um número inteiro positivo.`);
  }
  return valor;
}

// Caracteres de controle (exceto quebra de linha e TAB). O NUL (\u0000) é recusado pelo
// PostgreSQL em colunas de texto com um erro 500; aqui vira um 400 claro.
// biome-ignore lint/suspicious/noControlCharactersInRegex: é exatamente o que se quer detectar.
const CONTROLE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/;

export function texto(valor: unknown, campo: string, maximo: number): string {
  if (typeof valor !== "string") {
    throw new ErroDeValidacao(campo, `${campo} deve ser um texto.`);
  }
  if (CONTROLE.test(valor)) {
    throw new ErroDeValidacao(campo, `${campo} contém caracteres inválidos.`);
  }
  const limpo = valor.trim();
  if (limpo.length > maximo) {
    throw new ErroDeValidacao(campo, `${campo} passa de ${maximo} caracteres.`);
  }
  return limpo;
}

/** Texto opcional: ausente, null ou só espaços vira null. */
export function textoOpcional(valor: unknown, campo: string, maximo: number): string | null {
  if (valor === undefined || valor === null) return null;
  const limpo = texto(valor, campo, maximo);
  return limpo === "" ? null : limpo;
}

export function umDe<T extends string>(valor: unknown, campo: string, opcoes: readonly T[]): T {
  if (typeof valor !== "string" || !(opcoes as readonly string[]).includes(valor)) {
    throw new ErroDeValidacao(campo, `${campo} deve ser um de: ${opcoes.join(", ")}.`);
  }
  return valor as T;
}

/** O corpo de um POST precisa ser um objeto JSON (não lista, não texto). */
export function objeto(valor: unknown): Record<string, unknown> {
  if (typeof valor !== "object" || valor === null || Array.isArray(valor)) {
    throw new ErroDeValidacao("corpo", "O corpo do pedido deve ser um objeto JSON.");
  }
  return valor as Record<string, unknown>;
}

/** Termo de busca vindo da query string (?busca=...). */
export function termoDeBusca(valor: unknown): string {
  if (typeof valor !== "string") {
    throw new ErroDeValidacao("busca", "Informe o termo de busca (?busca=...).");
  }
  const termo = texto(valor, "busca", 60);
  if (termo.length < 2) {
    throw new ErroDeValidacao("busca", "Digite pelo menos 2 caracteres.");
  }
  return termo;
}

/**
 * Escapa os curingas do LIKE (% e _) e a barra: quem digita "50%" procura o texto "50%",
 * e não "50 seguido de qualquer coisa". O valor vai como parâmetro ($1), então isto não é
 * proteção contra injeção (o parâmetro já é), e sim busca correta.
 */
export function escaparLike(termo: string): string {
  return termo.replace(/[\\%_]/g, (c) => `\\${c}`);
}
