-- =====================================================================
-- Bootstrap: cria o usuário (role) e os bancos deste projeto dentro do
-- container PostgreSQL compartilhado com o Projeto 1.
--   :banco       banco principal (dados do projeto)
--   :banco_teste banco dos testes automatizados (apagado e recriado pelo pytest)
--   :bi_usuario, :bi_senha  usuário somente leitura do Power BI
--   :banco_app   banco da aplicação (API + tela do equipamentista)
--   :app_usuario, :app_senha  usuário da API (só movimenta pelas funções de regra)
--
-- Roda como superusuário, uma vez (e pode rodar de novo sem quebrar nada).
-- Não use diretamente: o `python -m almox.bootstrap` lê o .env, valida os
-- valores e envia este arquivo ao psql com as variáveis :usuario, :senha,
-- :banco e :banco_teste já definidas.
--
-- Por que não é uma migração do Alembic: criar role e banco são operações
-- do servidor inteiro (exigem superusuário) e CREATE DATABASE não roda
-- dentro de transação. As migrações rodam depois, já como o usuário do
-- projeto, dentro do banco dele.
--
-- Cada comando é montado com format(): %I cita identificadores e %L cita
-- literais (a senha), o que impede SQL injection pelas variáveis. O \gexec
-- executa cada linha resultante como um comando; o WHERE NOT EXISTS torna
-- tudo idempotente.
-- =====================================================================
\set ON_ERROR_STOP on

-- 1. Usuário do projeto: pode logar, mas não é superusuário, não cria
--    bancos, não cria roles e não ignora regras de segurança de linha.
SELECT format('CREATE ROLE %I LOGIN', :'usuario')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'usuario')
\gexec

-- Sempre reaplica atributos e senha: se o role já existia, fica em
-- sincronia com o .env e sem privilégios extras.
SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'usuario', :'senha'
)
\gexec

-- 2. Bancos do projeto (principal, de testes e da aplicação), pertencentes ao usuário do projeto.
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', b.nome, :'usuario', 'UTF8')
FROM unnest(ARRAY[:'banco', :'banco_teste', :'banco_app']) AS b(nome)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = b.nome)
\gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', b.nome, :'usuario')
FROM unnest(ARRAY[:'banco', :'banco_teste', :'banco_app']) AS b(nome)
\gexec

-- 3. Fuso horário na origem (lição do Projeto 1): toda sessão nestes bancos
--    enxerga horários em America/Recife; as colunas de data e hora são TIMESTAMPTZ.
SELECT format('ALTER DATABASE %I SET timezone TO %L', b.nome, 'America/Recife')
FROM unnest(ARRAY[:'banco', :'banco_teste', :'banco_app']) AS b(nome)
\gexec

-- 4. Por padrão o PostgreSQL deixa QUALQUER role conectar em qualquer banco
--    (privilégio CONNECT do PUBLIC). Aqui só o dono conecta (e, pelo passo 5, o
--    grupo de leitura do Power BI).
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', b.nome)
FROM unnest(ARRAY[:'banco', :'banco_teste', :'banco_app']) AS b(nome)
\gexec

-- 5. Leitura para o Power BI (menor privilégio). O grupo almox_leitura (sem login) recebe
--    as permissões nas migrações (SELECT só nos schemas bi, analise e dq); o usuário de
--    login do BI (nome e senha no .env) é membro do grupo e não tem mais nada.
SELECT 'CREATE ROLE almox_leitura NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_leitura')
\gexec

SELECT format('CREATE ROLE %I LOGIN', :'bi_usuario')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'bi_usuario')
\gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'bi_usuario', :'bi_senha'
)
\gexec

SELECT format('GRANT almox_leitura TO %I', :'bi_usuario')
\gexec

-- Também no banco da aplicação: o relatório operacional (posse, estoque, movimentação por
-- equipamentista) lê o "sistema vivo". O grupo só enxerga os schemas bi, analise e dq,
-- então não lê o core nem as senhas e sessões do schema app (testado em test_bi.py).
SELECT format('GRANT CONNECT ON DATABASE %I TO almox_leitura', b.nome)
FROM unnest(ARRAY[:'banco', :'banco_teste', :'banco_app']) AS b(nome)
\gexec

-- 6. Usuário da API (menor privilégio). O grupo almox_aplicacao (sem login) recebe as
--    permissões nas migrações: ler cadastros e estado, executar SÓ as funções de regra
--    que a tela usa, e nenhuma escrita direta em tabela do core. O usuário de login da API
--    (nome e senha no .env) é membro do grupo e não tem mais nada. Conecta no banco da
--    aplicação e no de testes (onde a API é testada), nunca no banco das análises.
SELECT 'CREATE ROLE almox_aplicacao NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao')
\gexec

SELECT format('CREATE ROLE %I LOGIN', :'app_usuario')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_usuario')
\gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'app_usuario', :'app_senha'
)
\gexec

SELECT format('GRANT almox_aplicacao TO %I', :'app_usuario')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO almox_aplicacao', b.nome)
FROM unnest(ARRAY[:'banco_app', :'banco_teste']) AS b(nome)
\gexec
