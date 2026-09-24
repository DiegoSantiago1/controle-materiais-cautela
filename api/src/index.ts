import { criarApp } from "./app.ts";
import { carregarArquivoEnv, carregarConfig, ErroDeConfiguracao } from "./config.ts";
import { criarPool } from "./db.ts";

carregarArquivoEnv();
let config: ReturnType<typeof carregarConfig>;
try {
  config = carregarConfig();
} catch (erro) {
  if (erro instanceof ErroDeConfiguracao) {
    console.error(`Erro de configuração: ${erro.message}`);
    process.exit(2);
  }
  throw erro;
}

const pool = criarPool(config.banco);
try {
  await pool.query("SELECT 1 FROM app.sessao LIMIT 1");
} catch (erro) {
  console.error(
    `Banco ${config.banco.banco} inacessível ou sem as tabelas da aplicação (${(erro as Error).message}).\n` +
      "Docker Desktop aberto? Já rodou 'python -m almox.bootstrap' e " +
      "'python -m almox.carga --recriar --banco app'?",
  );
  process.exit(1);
}

// Só na interface local (127.0.0.1): a API não fica exposta na rede.
// No Express 5 o callback do listen também é chamado quando dá ERRO (ex.: porta ocupada),
// com o erro como argumento. Ignorar o argumento fazia o servidor anunciar "no ar" e sair
// em silêncio com código 0.
const servidor = criarApp({ pool, cookieSeguro: config.cookieSeguro }).listen(
  config.portaHttp,
  "127.0.0.1",
  (erro?: Error) => {
    if (erro !== undefined) {
      const ocupada = (erro as NodeJS.ErrnoException).code === "EADDRINUSE";
      console.error(
        ocupada
          ? `A porta ${config.portaHttp} já está em uso (outro servidor aberto?). ` +
              "Feche-o ou defina ALMOX_API_PORT."
          : `Não foi possível iniciar o servidor: ${erro.message}`,
      );
      void pool.end().finally(() => process.exit(1));
      return;
    }
    console.log(`Tela do equipamentista: http://127.0.0.1:${config.portaHttp}`);
  },
);

for (const sinal of ["SIGINT", "SIGTERM"] as const) {
  process.on(sinal, () => {
    servidor.close(() => void pool.end().then(() => process.exit(0)));
  });
}
