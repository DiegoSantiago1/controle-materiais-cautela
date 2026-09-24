-- =====================================================================
-- Bootstrap: cria o usuário (role) e os bancos deste projeto dentro do
-- container PostgreSQL compartilhado com o Projeto 1.
--   :banco       banco principal (dados do projeto)
--   :banco_teste banco dos testes automatizados (apagado e recriado pelo pytest)
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

-- 2. Bancos do projeto (principal e de testes), pertencentes ao usuário do projeto.
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', b.nome, :'usuario', 'UTF8')
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = b.nome)
\gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', b.nome, :'usuario')
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
\gexec

-- 3. Fuso horário na origem (lição do Projeto 1): toda sessão nestes bancos
--    enxerga horários em America/Recife; as colunas de data e hora são TIMESTAMPTZ.
SELECT format('ALTER DATABASE %I SET timezone TO %L', b.nome, 'America/Recife')
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
\gexec

-- 4. Por padrão o PostgreSQL deixa QUALQUER role conectar em qualquer banco
--    (privilégio CONNECT do PUBLIC). Aqui só o dono conecta.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', b.nome)
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
\gexec
