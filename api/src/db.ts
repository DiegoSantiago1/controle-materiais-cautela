import pg from "pg";
import type { ConfigBanco } from "./config.ts";

// int8 (bigint) chega do driver como texto, porque pode passar do maior inteiro exato de
// um number do JavaScript (2^53 - 1). Os ids deste projeto ficam muito abaixo disso; a
// conversão deixa o JSON com números, e a checagem garante que nunca se perde precisão.
pg.types.setTypeParser(pg.types.builtins.INT8, (valor) => {
  const numero = Number(valor);
  if (!Number.isSafeInteger(numero)) throw new RangeError(`int8 fora do limite: ${valor}`);
  return numero;
});

export function criarPool(config: ConfigBanco): pg.Pool {
  return new pg.Pool({
    host: config.host,
    port: config.porta,
    database: config.banco,
    user: config.usuario,
    password: config.senha,
    max: 10,
    connectionTimeoutMillis: 5_000,
    // Nenhuma consulta da tela deveria passar de milissegundos; 5 s é o teto de segurança.
    statement_timeout: 5_000,
    application_name: "almox-api",
  });
}
