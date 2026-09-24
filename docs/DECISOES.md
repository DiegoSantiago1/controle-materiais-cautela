# Decisões técnicas

Registro das decisões de arquitetura do projeto: o contexto, a escolha, as alternativas descartadas e o custo de cada uma. Onde há número, ele foi medido.

## D1. Regras de negócio em funções do PostgreSQL

**Contexto.** As mesmas movimentações (retirada, devolução, estorno) serão feitas pelo gerador de dados em Python e, mais tarde, por uma API em Node/TypeScript.

**Decisão.** Cada operação é uma função PL/pgSQL no schema `core` (`core.registrar_retirada_unidade`, `core.registrar_retirada_consumo`, `core.estornar_movimentacao`...). Os clientes só chamam as funções.

**Por quê.** A regra existe num lugar só e vale para qualquer cliente. Validação, trava, atualização do estado e gravação do histórico acontecem numa única transação, dentro do banco.

**Alternativa descartada.** Regras na aplicação: exigiria reimplementar tudo em Node na fase da API, com risco de as duas versões divergirem.

**Custo.** PL/pgSQL é menos familiar que Python ou TypeScript e mais difícil de depurar. Compensado por testes que chamam cada função com entradas válidas e hostis.

## D2. Histórico imutável (ledger) + estado atual atualizado na mesma transação

**Decisão.** `core.movimentacao` só aceita `INSERT`: triggers bloqueiam `UPDATE`, `DELETE` e `TRUNCATE`. Um erro se corrige com uma movimentação `ESTORNO`, que aponta para a original. O estado atual (`unidade_patrimonial.status/detentor_id`, `saldo_consumo.quantidade`) é atualizado junto, na mesma transação.

**Por quê.** Rastreabilidade completa: quem fez, quando, o quê, saldo antes e depois. E o estado atual pode ser auditado contra o histórico: a view `core.vw_divergencia_estado` reconstrói o estado pelo histórico e lista qualquer diferença (tem que estar sempre vazia).

**Alternativas descartadas.**
- Saldo só derivado (`SUM` do histórico): fonte única da verdade, mas cada consulta de saldo varre o histórico e não dá para impedir saldo negativo com um `CHECK` simples.
- Saldo editável + log à parte: o log pode divergir do saldo e deixa de ser confiável.

**Limitação conhecida.** O dono das tabelas pode desligar triggers. A proteção completa vem na fase da aplicação: a API usará um usuário sem permissão de `UPDATE`/`DELETE` nas tabelas, com acesso só às funções.

## D3. `SELECT ... FOR UPDATE` contra concorrência

**Decisão.** Toda função trava a linha do estado (a unidade ou o saldo) antes de validar.

**Medido.** Teste com 20 retiradas simultâneas de 1 unidade sobre um saldo de 10:
- **com** a trava: 10 sucessos, 10 recusas com "estoque insuficiente" (`ALM01`), saldos registrados de 10 até 0 sem repetição;
- **sem** a trava (experimento descartável): as 10 retiradas que passaram registraram todas `saldo_antes = 10` (histórico corrompido), e as 10 recusas vieram como violação genérica de `CHECK`, não como regra de negócio. O saldo final só ficou certo porque o `CHECK (quantidade >= 0)` segurou.

**Lição.** O `CHECK` no banco é a última linha de defesa (o saldo não fica negativo), mas não protege a coerência do histórico. A trava protege as duas coisas.

## D4. Integridade no banco, não só na aplicação

Exemplos do que o banco recusa sozinho, mesmo com um `INSERT` direto:

- **FK composta** `(material_tipo_id, controle)`: é impossível criar uma unidade patrimonial de um material de consumo, ou um saldo de um material patrimonial.
- **FK composta** `(unidade_id, material_tipo_id)` no histórico: a movimentação não pode citar um material diferente do da unidade.
- **`CHECK`s de coerência**: unidade cautelada tem detentor e vice-versa; sem BMP só aguardando tombamento; `saldo_depois = saldo_antes + variacao`; nada no futuro.
- **Índice único parcial**: o mesmo número de série não se repete no mesmo tipo de material (erro real das planilhas de carga), mas várias unidades podem não ter série.
- **Domain `core.nome`**: nomes sem espaço em branco nas pontas, sem espaços duplos, sem caracteres de controle, únicos sem diferenciar maiúsculas. Um teste revelou que a primeira versão (com `btrim`) aceitava TAB no início, porque `btrim` só remove o caractere espaço. Corrigido com expressão regular.

## D5. Erros de regra com SQLSTATE próprio

Cada violação de regra levanta um código (`ALM01` estoque insuficiente, `ALM04` devolução por quem não é o detentor etc.). A aplicação e os testes identificam o motivo pelo código, sem depender do texto da mensagem, que pode mudar.

## D6. Ordem cronológica por item

Uma movimentação não pode ser anterior à última do mesmo item (unidade ou material). É o que garante que o estado reconstruído pelo histórico (`ORDER BY ocorrida_em, id`) é o mesmo do estado atual. Custo: lançamentos retroativos fora de ordem são recusados; a correção é via estorno.

## D7. Banco de testes separado, recriado pelas migrações

**Contexto.** Os testes de concorrência precisam de `COMMIT` real, e o histórico é imutável: não daria para limpar os dados depois no banco principal.

**Decisão.** Um segundo banco (`almoxarifado_teste`). Cada execução do `pytest` sobe todas as migrações, desce todas (conferindo que nada sobrou) e sobe de novo. Assim os `downgrade` também são testados. A configuração recusa um banco de testes com o mesmo nome do principal.

## D8. Alembic com SQL escrito à mão

As migrações usam `op.execute("""SQL""")`, sem geração automática a partir de modelos (não há ORM). O SQL fica visível e revisável, como no Projeto 1, e o Alembic registra em `alembic_version` o que foi aplicado. Novas migrações já saem formatadas pelo `ruff` (hook do Alembic).

## D9. Conexão por `127.0.0.1`, não `localhost`

**Medido.** No Windows, `localhost` resolve primeiro para o IPv6 `::1`, mas o container publica a porta só em IPv4. Cada conexão esperava o timeout do `::1`: 5,09 s por `localhost` contra 0,02 s por `127.0.0.1`. A suíte de testes caiu de 47,9 s para 3,8 s.

## D10. Modelagem

- **Categoria e subcategoria em duas tabelas**, e não uma tabela autorreferenciada: a profundidade é sempre dois níveis, e duas tabelas garantem isso sem truques.
- **Prazo de devolução em horas** por tipo de material (rádio: 12 h, um turno); "0 dias" ficaria atrasado no mesmo instante.
- **Pessoa com `data_saida`** (transferência). Uma cautela aberta com quem já saiu da unidade é o caso real de material "não localizado".
- **Códigos auxiliares fora do modelo**: a planilha que serviu de referência tinha outros códigos além do número de patrimônio, cujo significado não foi confirmado. Não se modela o que não se sabe explicar.
