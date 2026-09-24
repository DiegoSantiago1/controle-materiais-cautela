-- =====================================================================
-- Bootstrap: cria o usuário (role) e o banco deste projeto dentro do
-- container PostgreSQL compartilhado com o Projeto 1.
--
-- Roda como superusuário, uma vez (e pode rodar de novo sem quebrar nada).
-- Não use diretamente: o scripts/criar_banco.py lê o .env, valida os
-- valores e envia este arquivo ao psql com as variáveis :usuario, :senha
-- e :banco já definidas.
--
-- Por que não é uma migração do Alembic: criar role e banco são operações
-- do servidor inteiro (exigem superusuário) e CREATE DATABASE não roda
-- dentro de transação. As migrações rodam depois, já como o usuário do
-- projeto, dentro do banco dele.
--
-- Cada comando é montado com format(): %I cita identificadores e %L cita
-- literais (a senha), o que impede SQL injection pelas variáveis. O \gexec
-- executa o texto resultante; o WHERE NOT EXISTS torna tudo idempotente.
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

-- 2. Banco do projeto, pertencente ao usuário do projeto.
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', :'banco', :'usuario', 'UTF8')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'banco')
\gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', :'banco', :'usuario')
\gexec

-- 3. Fuso horário na origem (lição do Projeto 1): toda sessão neste banco
--    enxerga horários em America/Recife; as colunas serão TIMESTAMPTZ.
SELECT format('ALTER DATABASE %I SET timezone TO %L', :'banco', 'America/Recife')
\gexec

-- 4. Por padrão o PostgreSQL deixa QUALQUER role conectar em qualquer banco
--    (privilégio CONNECT do PUBLIC). Aqui só o dono conecta.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'banco')
\gexec
