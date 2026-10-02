# Controle de Materiais e Cautela

**Análise de dados do controle de material de uma unidade logística (dados fictícios): carga patrimonial, cautelas, uso de equipamentos e estoque de consumo, com PostgreSQL, SQL analítico, Python (Pandas/NumPy) e Power BI. Mais um sistema web de controle (retirada, devolução, posse, estoque e administração, no computador e no celular) que grava pelas mesmas regras do banco.**

> Projeto 2 do meu portfólio de Dados, na sequência do [Painel de Vendas](https://github.com/DiegoSantiago1/analise-vendas-concessionaria). Dados, análises e sistema concluídos; o modelo do Power BI está pronto e documentado, e a montagem do relatório é a próxima etapa.

## O problema

Trabalhei na Força Aérea Brasileira em funções administrativas, incluindo controle de materiais e conferência de carga patrimonial. Esse controle costuma viver em planilhas, e os problemas se repetem: o mesmo item escrito de vários jeitos, número de patrimônio em branco ou digitado errado, material que a planilha diz estar no depósito mas está emprestado com alguém, ferramenta que nunca volta no prazo, item de consumo que acaba antes da compra chegar.

Este projeto transforma essa rotina em quatro perguntas de negócio, respondidas com dados:

1. **Conferência:** onde a planilha de carga não bate com o cadastro, e onde os erros se concentram?
2. **Cautela:** quem está com cada material, quem atrasa a devolução, e o atraso é da pessoa ou do processo?
3. **Uso:** o que sobra, o que falta e o que se desgasta?
4. **Consumo:** que item vai faltar, e quais têm o estoque mínimo mal definido?

> **Todos os dados são fictícios**, gerados em Python. Nenhuma informação real (pessoas, unidades, locais, números de patrimônio) está neste repositório, e o projeto não inclui armamento de fogo, munição nem material de armaria (tonfa, espadim e sabre entram como material de controle de distúrbios e de cerimonial).

## Resultados

| # | Pergunta | Principal resultado | Detalhe |
|---|---|---|---|
| A1 | Conferência da carga | 47,8% das 358 linhas têm problema, mas 146 são só de forma (corrigidas automaticamente); **24 vão para verificação humana**. O Depósito Central tem 15,5% das linhas e **43,9% dos problemas**. | [notebook](notebooks/01_conferencia.ipynb) |
| A2 | Cautela e atrasos | O atraso é sobretudo **de processo**: ferramentas elétricas atrasam 45% na Manutenção e 5% fora dela. Um ranking ingênuo acusaria 5 pessoas pontuais; ajustando pelo material, com intervalo de Wilson, **nenhuma pontual é apontada** e os 4 reincidentes plantados são encontrados. | [notebook](notebooks/02_cautela.ipynb) |
| A3 | Uso e ociosidade | 4 tipos concentram 81% das cautelas. **R$ 64 mil parados** em 6 tipos que não saíram no ano, enquanto esmerilhadeira, lavadora, notebook e ferramentas elétricas passam de **10 a 57 dias sem nenhuma unidade na prateleira**. | [notebook](notebooks/03_uso.ipynb) |
| A4 | Consumo e ruptura | O mínimo do toner é **7 vezes menor** que o ponto de reposição (56 dias sem toner no ano). A análise acha os 3 mínimos mal calibrados, o fornecedor lento (38 dias contra 13) e os 3 excessos: **24 de 24 materiais**. | [notebook](notebooks/04_consumo.ipynb) |

<p align="center">
  <img src="docs/img/a2_atraso_pessoa_x_processo.png" width="49%" alt="Atraso por pessoa: taxa observada, intervalo de Wilson e taxa esperada pelo material">
  <img src="docs/img/a4_minimo_x_ponto_de_reposicao.png" width="49%" alt="Mínimo cadastrado contra o ponto de reposição calculado, por material">
</p>

<p align="center">
  <img src="docs/img/a4_saldo_do_toner.png" width="80%" alt="Saldo diário do toner: seis rupturas no ano">
</p>

### Como sei que as análises estão certas

Os dados foram gerados com **padrões plantados e documentados** (ver [PLAN](docs/PLAN.md), P1 a P16) e com um **gabarito** que as análises não usam para concluir, só para conferir no fim:

- **A1:** a conferência acertou os 243 erros injetados na planilha padrão e, em sete outros conjuntos que as regras nunca tinham visto (1.750 erros injetados), deixou de detectar **2** e acusou **1** a mais.
- **A2:** achou os 4 reincidentes sem apontar nenhuma pessoa pontual.
- **A4:** 24 de 24 materiais classificados corretamente, também em quatro conjuntos fora da amostra, com margem folgada.

Validar fora da amostra revelou defeitos reais, corrigidos na regra e não no número (detalhes em [DECISOES](docs/DECISOES.md), D14 a D17).

## Arquitetura

```mermaid
flowchart LR
    G["Gerador Python<br/>(12 meses, semente fixa,<br/>padrões P1-P16)"] --> CSV["CSV + manifesto<br/>SHA-256"]
    CSV --> C["Carga<br/>python -m almox.carga"]
    C -->|"cada evento pela<br/>função de regra"| CORE[("core<br/>cadastros, estado,<br/>histórico imutável")]
    CSV -->|planilha suja| STG[("staging")]
    CORE --> AN["analise<br/>views SQL"]
    STG --> AN
    CORE --> DQ["dq<br/>10 regras de qualidade"]
    CORE --> BI["bi<br/>modelo estrela"]
    AN --> NB["Notebooks<br/>Pandas / NumPy"]
    BI --> PBI["Power BI<br/>(usuário só leitura)"]
    AN --> PBI
    C -->|"mesmos dados + catálogo militar<br/>+ setembro simulado"| APP[("almoxarifado_app")]
    TELA["Tela web<br/>(computador e celular)"] --> API["API Node/TypeScript"]
    API -->|"só funções app.*<br/>com o token da sessão"| APP
    APP -->|"bi operacional"| PBI
```

- **`core`:** cadastros, estado atual e um **histórico de movimentações imutável** (só INSERT; triggers bloqueiam UPDATE, DELETE e TRUNCATE; erro se corrige com estorno). Toda movimentação passa por uma **função PL/pgSQL** que confere o perfil, trava a linha (`SELECT ... FOR UPDATE`), valida a regra e grava tudo numa transação.
- **`staging`:** a planilha de carga "suja", como veio, e o gabarito dos erros.
- **`analise`:** as quatro análises como views SQL (CTEs, window functions, *gaps and islands*, similaridade de trigramas, Levenshtein).
- **`dq`:** qualidade de dados, só com o que constraints não conseguem impor (encadeamento do histórico via `LAG`, estado × histórico, etc.).
- **`bi`:** modelo estrela para o Power BI, lido por um usuário **somente leitura** que não enxerga `core` nem `staging` ([guia](docs/POWERBI.md)).
- **`app`:** login e sessões (senha em `scrypt`, sessão guardada só como hash) e as funções que a API pode executar, todas exigindo uma sessão válida.

## Aplicação: o sistema do almoxarifado

No balcão, quem entrega o material precisa registrar **quem levou o quê, quanto, quem entregou e quando**, em poucos toques, e ver na hora o que está vencido. Hoje isso costuma ser caderno ou planilha, justamente de onde vêm os erros que a conferência (A1) e a análise de atrasos (A2) encontraram.

<p align="center">
  <img src="docs/img/app_inicio.png" width="49%" alt="Início: ações rápidas, contadores operacionais, posses vencidas e últimas movimentações">
  <img src="docs/img/app_nova_retirada.png" width="49%" alt="Nova retirada: militar, vários materiais com quantidade e o resumo com quem entrega">
  <img src="docs/img/app_cautelas_em_aberto.png" width="49%" alt="Em posse: militar, material, quantidade, retirada, quem entregou e prazo">
  <img src="docs/img/app_devolucao.png" width="49%" alt="Receber devolução: unidades marcadas por BMP e o estado em que voltaram">
  <img src="docs/img/app_estoque.png" width="49%" alt="Estoque: total, disponível, em posse, manutenção, mínimo e o painel com cada unidade">
  <img src="docs/img/app_tema_escuro.png" width="49%" alt="Histórico no tema escuro, com o ciclo retirada, posse e devolução">
</p>

- **Militares identificados pelo nome de guerra** e pelo posto/graduação (S2 a CEL): "SGT SOUZA" é como o equipamentista procura no balcão.
- **Nova retirada:** o militar, um ou mais materiais (por quantidade, e o banco escolhe as unidades, ou pelo BMP da etiqueta), o estado em que saíram (bom ou regular, com observação) e a finalidade. Tudo numa transação, com um **código de operação** que liga as unidades do mesmo atendimento; sai um comprovante com os BMPs e os prazos.
- **Receber devolução:** marca as unidades que voltaram (pode ser parte de uma retirada) e o estado: avariado vai para manutenção, inservível para baixa. A retirada original continua no histórico.
- **Em posse:** quem está com cada material, desde quando, quem entregou e o prazo, com as vencidas primeiro, busca e filtros.
- **Estoque:** total, disponível, em posse, em manutenção, indisponível e mínimo por material, atualizados a cada movimento, e o painel de cada material com todas as unidades. Estoque negativo é impossível: o banco recusa.
- **Histórico** com filtros e o **ciclo** de cada atendimento (retirada → posse → devolução, com quem entregou e quem recebeu).
- **Administração:** materiais e categorias, militares (cadastro, edição, saída da unidade), usuários e permissões (perfil, ativação, senha) e a auditoria de cada alteração.
- **Sem gráficos na tela**, de propósito: ela é para operar. Análise fica no Power BI (relatório operacional na [Parte A do guia](docs/POWERBI.md)).

**Perfis:** o **equipamentista** opera o balcão (retirada, devolução, posse, estoque, histórico); o **administrador** tem acesso completo; há ainda estoquista (balcão + entradas e ajustes) e consulta (só leitura). A tela esconde o que o perfil não pode, a API responde 403 e, por fim, a função do banco confere o perfil de novo.

**A API não reescreve regra nenhuma.** Ela chama as mesmas funções do banco que a carga usa, e o usuário dela **não tem permissão de gravar em nenhuma tabela** do `core`. Desde a migração 0015 ele executa só funções `app.*`, que recebem o **hash do token da sessão** e descobrem no banco quem está logado (D24): mesmo com uma injeção de SQL na API, ninguém age como administrador sem o token de um administrador logado.

**Segurança testada** (D21): senha com `scrypt`, sessão em cookie `HttpOnly` + `SameSite=Strict` guardada só como hash, limite de tentativas de login, a mesma resposta (e o mesmo tempo) para login inexistente e senha errada, proteção contra CSRF (JSON obrigatório + conferência de origem), CSP sem script inline e nenhum dado inserido como HTML na tela (testado com um nome de material contendo `<img onerror>`). A aplicação usa um **banco próprio** (D19), com o catálogo militar e um mês de uso simulado (D23), para não mexer nos números das análises.

## Decisões técnicas (resumo)

As decisões, com contexto, alternativas e o que foi medido, estão em [docs/DECISOES.md](docs/DECISOES.md). Os destaques:

- **Regra de negócio no banco (D1).** O gerador e a futura API chamam as mesmas funções. A carga passa cada um dos 15.751 eventos por elas, o que achou um defeito do próprio gerador.
- **`FOR UPDATE` provado, não suposto (D3).** Removida a trava num experimento, 20 retiradas simultâneas corromperam o histórico: todas registraram o mesmo saldo anterior. Com a trava, exatamente 10 de 20 passam num saldo de 10.
- **Integridade no banco (D4).** FKs compostas impedem misturar material patrimonial e de consumo; cada CHECK tem um teste que tenta violá-lo.
- **Pessoa x processo com estatística (D16).** A taxa esperada é calculada pela mistura de materiais, e a pessoa só é apontada se o limite inferior do intervalo de Wilson ficar acima dela.
- **Demanda censurada (D17).** Dias sem estoque ficam fora da média de demanda, senão os itens que mais faltam são os mais subestimados.
- **Menor privilégio no Power BI (D18).** Um usuário que só lê, com funções de escrita inacessíveis. Isso inclui a armadilha de views com funções `SECURITY INVOKER`.
- **Quantidade sem perder o BMP (D25).** "3 escudos" escolhe 3 unidades com `FOR UPDATE SKIP LOCKED`: dois balcões ao mesmo tempo nunca pegam a mesma unidade (testado com 8 conexões simultâneas), e cada unidade passa pela regra que já existia.
- **O banco descobre quem está logado (D24).** As funções da aplicação recebem o hash do token, não um id de usuário: fecha a limitação que a D20 registrava.

## Qualidade

- **574 testes em Python** (`pytest`): integridade do schema com entradas hostis, regras de movimentação, retirada e devolução por quantidade, administração e auditoria, sessão válida nas funções da aplicação, concorrência com COMMIT real, reprodutibilidade do gerador e da atividade simulada, os padrões P1 a P16, fidelidade campo a campo da carga, cada regra de qualidade (injetando a violação), cada análise e as permissões do Power BI e da API.
- **133 testes da API** (`node:test`, por HTTP, como o navegador): login e sessão, força bruta, a matriz de permissões (o equipamentista recebe 403 em toda rota de administrador), pedidos hostis (ids falsos, listas com repetição, JSON quebrado, caractere nulo, corpo gigante, injeção de SQL), CSRF, cabeçalhos de segurança, as regras chegando como status HTTP, retirada com vários materiais tudo-ou-nada e 10 retiradas simultâneas da mesma unidade (passa exatamente uma).
- **Navegador de verdade** (Playwright, Chromium, 1440×900 e 390×844): os fluxos de balcão e de administração sem nenhum erro de console, inclusive XSS e queda de sessão depois de troca de perfil.
- Banco de testes separado, recriado pelas migrações a cada execução: sobe, desce e sobe de novo, o que também testa os *downgrades*.
- `ruff` (lint, formatação e regras de segurança, inclusive nos notebooks) e `mypy --strict`.
- **Reprodutível:** mesma semente e mesma data final geram arquivos byte a byte idênticos (SHA-256 no [manifesto](data/gerado/manifesto.json)).

## Tecnologias e por quê

| Tecnologia | Para quê |
|---|---|
| PostgreSQL 16 (Docker) | integridade no banco, funções de regra, views analíticas, extensões `pg_trgm`, `fuzzystrmatch`, `unaccent` |
| SQL | CTEs, window functions (`LAG`, `LEAD`, somas acumuladas, `RANK`), *gaps and islands*, `LATERAL` |
| Python, NumPy, Pandas | gerador de dados, intervalo de Wilson, ponto de reposição, avaliação contra o gabarito, notebooks |
| Alembic | migrações versionadas com SQL escrito à mão (16 migrações) |
| Power BI | relatórios operacional e analítico sobre o modelo estrela (guia e tema em `docs/`) |
| Node 24, TypeScript, Express 5, `pg` | API do sistema, com SQL escrito à mão |
| HTML, CSS, JavaScript | tela responsiva, módulos ES por página, sem framework nem etapa de build |
| pytest, ruff, mypy | testes, lint e tipos (Python) |
| `node:test`, Biome, `tsc` | testes, lint e tipos (API e tela) |

## Como rodar

Requisitos: Python 3.14, Docker Desktop e um container PostgreSQL 16 rodando. Este projeto usa o mesmo container do [Painel de Vendas](https://github.com/DiegoSantiago1/analise-vendas-concessionaria) (`docker compose up -d` na pasta dele), com bancos e usuários próprios.

```bash
# 1. Ambiente Python
python -m venv .venv
.venv\Scripts\activate            # Windows (no Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt

# 2. Configuração: copie o modelo e troque as duas senhas (dono do banco e leitura do BI)
copy .env.example .env            # Linux/macOS: cp .env.example .env

# 3. Cria os usuários e os bancos no container (pode rodar de novo sem problema)
python -m almox.bootstrap

# 4. Aplica as migrações
alembic upgrade head

# 5. Gera os dados fictícios (semente 42, 12 meses até 31/08/2026) em data/gerado/
python -m almox.gerador

# 6. Carrega no banco, passando cada evento pelas funções de regra (~1 min).
#    --recriar é obrigatório: apaga e recria o schema (o histórico é imutável).
python -m almox.carga --recriar
```

### O sistema (API e tela)

Requisito extra: Node 24. Com os passos 1 a 4 feitos:

```bash
# 7. Banco da aplicação: os mesmos dados, o catálogo militar e setembro de uso (~1,5 min)
python -m almox.carga --recriar --banco app

# 8. Dependências da API e senha dos usuários (digitada, não aparece na tela)
cd api
npm install
npm run definir-senha -- rafaela.01   # ADMINISTRADOR
npm run definir-senha -- enzo.04      # EQUIPAMENTISTA (heitor.09 é CONSULTA)

# 9. Sobe a API e a tela em http://127.0.0.1:3334
npm start
```

Testes da API: `python -m almox.migracoes teste` (uma vez, deixa o banco de testes no schema atual) e depois `npm run verificar` (lint, tipos e testes).

Os notebooks são salvos já executados. Para reexecutar um deles (com o banco carregado): `jupyter nbconvert --to notebook --execute --inplace notebooks/01_conferencia.ipynb`. Para rodar as checagens de qualidade: `SELECT dq.executar();` e depois `SELECT * FROM dq.vw_ultima_execucao;`.

**Atenção:** como os bancos ficam no container do outro projeto, um `docker compose down -v` lá apaga também estes (o `-v` remove o volume). Para recriar, repita os passos 3 a 8.

### Verificações

```bash
ruff format --check .             # formatação
ruff check .                      # lint (inclui regras de segurança)
mypy                              # tipos (modo strict)
pytest                            # todos os testes (precisa do banco; ~2 min)
pytest -m "not lento"             # sem as cargas completas
pytest -m "not integracao"        # só os testes que não usam o banco
```

## Estrutura

```
db/bootstrap.sql              usuários e bancos (superusuário, idempotente)
db/migracoes/versions/        16 migrações: core, staging, análises, dq, bi, app, operação, administração
src/almox/gerador/            gerador de dados sintéticos (catálogo, simulação, planilha)
src/almox/carga.py            carga pelas funções de regra, com conferência cruzada
src/almox/complemento.py      catálogo militar e militares do banco da aplicação
src/almox/atividade.py        setembro de uso simulado (plano puro + execução pelas regras)
src/almox/analise/            conferência, cautela, uso e consumo (usados pelos notebooks)
notebooks/                    as quatro análises, executadas, com insights
tests/                        574 testes (Python)
api/                          API Node/TypeScript (rotas por assunto) e 133 testes (node:test)
web/                          tela (HTML, CSS, JavaScript; uma página por módulo em js/paginas/)
docs/                         plano, decisões técnicas, guia e tema do Power BI
```

## Limitações e próximos passos

- **Relatório Power BI:** os dois modelos estão prontos, testados e documentados, com números de referência; a montagem do arquivo `.pbix` é a próxima etapa.
- **Aplicação:** estorno pela tela e devolução feita por outra pessoa (em nome do detentor) ainda não existem; o estorno continua só pela função do banco. O limite de tentativas de login fica na memória de um processo, e a API roda só em `127.0.0.1`, sem HTTPS (para publicar, entraria um proxy com TLS e o cookie `Secure`).
- Os padrões dos dados foram plantados. As análises foram validadas por conseguirem reencontrá-los, o que mostra que o método funciona, mas não substitui dados reais.
