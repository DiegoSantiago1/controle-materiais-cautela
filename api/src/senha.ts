/**
 * Hash de senha com scrypt (módulo crypto do Node, sem dependência externa).
 *
 * Por que scrypt e não SHA-256: um hash rápido deixa um atacante com o banco vazado testar
 * bilhões de senhas por segundo. O scrypt é lento de propósito e gasta memória (N=2^17,
 * r=8: 128 MiB por cálculo, parâmetros mínimos recomendados pela OWASP), o que torna o
 * ataque em massa caro, inclusive em GPU. O sal aleatório faz duas senhas iguais terem
 * hashes diferentes.
 *
 * Formato guardado: scrypt$N$r$p$sal$hash (sal e hash em base64url). Os parâmetros ficam
 * junto do hash: se um dia forem aumentados, as senhas antigas continuam conferindo.
 */
import { randomBytes, scrypt, timingSafeEqual } from "node:crypto";

const N = 2 ** 17;
const R = 8;
const P = 1;
const TAMANHO_HASH = 32;
const TAMANHO_SAL = 16;
export const SENHA_MIN = 10;
export const SENHA_MAX = 128;

// Limite de memória acima do que os parâmetros exigem (128 * N * r = 128 MiB).
const MEMORIA_MAX = 256 * 1024 * 1024;

function derivar(senha: string, sal: Buffer, n: number, r: number, p: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scrypt(
      senha.normalize("NFC"),
      sal,
      TAMANHO_HASH,
      { N: n, r, p, maxmem: MEMORIA_MAX },
      (erro, chave) => (erro ? reject(erro) : resolve(chave)),
    );
  });
}

export async function gerarHash(senha: string): Promise<string> {
  const sal = randomBytes(TAMANHO_SAL);
  const hash = await derivar(senha, sal, N, R, P);
  return ["scrypt", N, R, P, sal.toString("base64url"), hash.toString("base64url")].join("$");
}

const FORMATO = /^scrypt\$([0-9]+)\$([0-9]+)\$([0-9]+)\$([A-Za-z0-9_-]+)\$([A-Za-z0-9_-]+)$/;

/**
 * Confere a senha com o hash guardado. Comparação em tempo constante (timingSafeEqual):
 * uma comparação comum para no primeiro byte diferente, e o tempo de resposta vazaria
 * quantos bytes estão certos.
 */
export async function conferirSenha(senha: string, guardado: string): Promise<boolean> {
  const partes = FORMATO.exec(guardado);
  if (partes === null) return false;
  // Os grupos sempre existem quando a expressão casa; o "" só satisfaz o tipo.
  const [, n = "", r = "", p = "", sal = "", hash = ""] = partes;
  const esperado = Buffer.from(hash, "base64url");
  // Parâmetros absurdos (hash adulterado no banco) poderiam travar o servidor.
  if (Number(n) > 2 ** 20 || Number(r) > 16 || Number(p) > 4 || esperado.length !== TAMANHO_HASH) {
    return false;
  }
  const calculado = await derivar(
    senha,
    Buffer.from(sal, "base64url"),
    Number(n),
    Number(r),
    Number(p),
  );
  return timingSafeEqual(calculado, esperado);
}

// Hash de uma senha aleatória descartada (ninguém a conhece), com os mesmos parâmetros.
// Fixo, e não gerado na hora: gerar custaria um scrypt a mais no primeiro login com
// usuário inexistente (medido: 0,62 s contra 0,30 s), e essa diferença já vazaria.
const HASH_FICTICIO =
  "scrypt$131072$8$1$lQBGejb_V45BOWiPeoqlJQ$_5hMqkedT1suEpCA4_M4yQxIdnbvAkgVqFVXplG_idU";

/**
 * Login com usuário inexistente também gasta um cálculo de scrypt. Sem isso, "usuário não
 * existe" responderia na hora e "senha errada" demoraria: pelo tempo, um atacante
 * descobriria quais logins existem.
 */
export async function gastarTempoDeConferencia(senha: string): Promise<void> {
  await conferirSenha(senha, HASH_FICTICIO);
}
