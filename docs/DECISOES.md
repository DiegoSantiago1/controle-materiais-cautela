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

## D11. Carga pelas funções do banco, com conferência cruzada

**Decisão.** A carga dos dados gerados não faz `INSERT` direto no histórico: cada um dos ~15,7 mil eventos passa pela função de regra correspondente, numa única transação. No fim, a view de divergência precisa estar vazia e o estado final de cada unidade no banco precisa bater com o estado que o gerador calculou em Python.

**Por quê.** É um teste cruzado entre duas implementações independentes das mesmas regras. Ele achou um defeito real no gerador: um "conserto concluído" lançado num sábado pelo equipamentista de serviço, que o banco recusou (só estoquista ou administrador mudam a situação de uma unidade).

**Medido.** ~50 s para 15,7 mil eventos (3,2 ms por evento): 1,45 ms de ida e volta de rede (Docker Desktop no Windows) e o resto de trabalho no servidor (cada função faz umas dez operações). Um *pipeline* do psycopg economizaria no máximo a parte da rede, com tratamento de erro bem mais difícil (identificar o evento recusado). Descartado: a carga roda uma vez.

## D12. Dados gerados fora do git, manifesto dentro

Os CSVs (~1,6 MB) são reproduzíveis pelo gerador e não são versionados. O `manifesto.json` é: guarda a semente, a data final e o SHA-256 de cada arquivo. Regenerar e comparar os hashes é a prova de reprodutibilidade (conferida: 12 de 12 arquivos idênticos).

## D13. Estoque mínimo: a fórmula que o gerador usa para "bem calibrado"

A primeira versão calculava o mínimo só com a demanda média e o prazo médio. Medindo os dados gerados, itens "bem calibrados" faltavam 4 a 7 vezes por ano, o que apagava o contraste com os mal calibrados. Faltavam dois termos: a **variação do prazo do fornecedor** e o **pico sazonal**. A fórmula completa do estoque de segurança,

    minimo = d*L + z * raiz(L * var_d + d^2 * var_L)

aplicada sobre a demanda do mês de pico, deixou a maioria dos bem calibrados sem nenhuma falta no ano, enquanto os mal calibrados faltam 5 a 7 vezes (medido em 5 sementes). A análise de consumo (Fase 2) terá de reencontrar isso só a partir do histórico.

## D14. Conferência: detecção em SQL, avaliação em Python, validação fora da amostra

**Decisão.** A detecção dos erros da planilha é uma view (`analise.vw_conferencia_planilha`): normalização de texto (sem acento, abreviações por extenso), similaridade de trigramas (`pg_trgm`) para achar o material mais parecido, distância de Levenshtein (`fuzzystrmatch`) para BMP com dígito trocado, e o estado atual do `core` para divergências. As três extensões são "trusted": o dono do banco instala sem superusuário. O Python lê a view, monta a planilha corrigida e mede precisão e revocação contra o gabarito.

**Por quê.** A regra fica perto dos dados e é reaproveitável (o Power BI e a futura API leem a mesma view); o Pandas fica com o que ele faz melhor (avaliação, tabelas e gráficos).

**Como evitei ajustar as regras aos dados.** 100% de acerto na base usada para construir as regras não prova nada. A view foi avaliada em sete sementes que nunca tinha visto (1.750 erros injetados): 2 não detectados e 1 falso positivo, todos o mesmo caso-limite (texto quebrado pela extração combinado com outro erro na mesma palavra), deixado documentado em vez de remendado. A avaliação fora da amostra revelou três defeitos reais, corrigidos na regra:
- abreviação expandida sem o ponto (`'2 port as'` virava "portátil");
- regras de nome exclusivas entre si (uma linha pode ter formatação diferente **e** digitação);
- BMP vizinho escolhido só pela distância. Os BMPs de um lote são consecutivos, então vários candidatos ficam a 1 ou 2 dígitos. O número de série desempata, mas só se o dono dela não estiver listado com o próprio BMP (senão a série foi copiada).

## D15. Qualidade de dados: só checar o que o banco não impede

**Contexto.** O plano listava checagens como "código duplicado", "saldo negativo", "movimentação sem usuário" e "quantidade inválida".

**Decisão.** Essas já são impossíveis no `core` (UNIQUE, CHECK, NOT NULL, FK), e os testes de schema provam isso tentando violá-las. Uma checagem que nunca pode encontrar nada seria teatro. O schema `dq` cobre o que constraints não expressam:

| Regra | O quê | Por que constraint não cobre |
|---|---|---|
| DQ01 | estado atual ≠ histórico | compara duas tabelas |
| DQ02 | `saldo_antes` ≠ `saldo_depois` da anterior (`LAG`) | depende da linha anterior |
| DQ03 | `status_anterior` ≠ `status_novo` da anterior (`LAG`) | idem |
| DQ04 | unidade cautelada a pessoa já transferida | depende de data e de outra tabela |
| DQ05 | retirada para pessoa fora do seu período | idem |
| DQ06 | operação de um perfil que não poderia (hoje) | o perfil pode mudar depois |
| DQ07 | unidade sem entrada no histórico | exige outra tabela |
| DQ08 | material ativo sem unidades nem saldo | cadastro órfão |
| DQ09, DQ10 | planilha: BMP fora do formato, campo obrigatório vazio | o staging aceita tudo de propósito |

`dq.executar()` roda todas as regras e grava cada ocorrência em `dq.ocorrencia`. O SQL dinâmico usa o nome da view validado por CHECK e citado com `%I`.

**Como sei que funcionam.** "Zero ocorrências" também é o que uma regra quebrada daria. Cada regra tem um teste que injeta a violação por fora das funções (INSERT/UPDATE direto) e confere que ela é registrada, mais um controle negativo com dados válidos. A DQ02 é a checagem que faltava: o experimento sem `FOR UPDATE` (D3) corrompeu o histórico sem mudar a soma, e a DQ01 não percebeu.

## D16. Atraso: separar pessoa de processo, com evidência estatística

**Contexto.** A taxa de atraso crua por pessoa mistura quem a pessoa é com o material que ela usa. Na Manutenção, ferramentas elétricas atrasam 45% das vezes; fora dela, 5%.

**Decisão.** Cada pessoa tem uma **taxa esperada**: a média, nas cautelas dela, da taxa geral do tipo de material. A pessoa só é apontada se o **limite inferior do intervalo de Wilson (95%)** da taxa observada ficar acima da esperada, com pelo menos 20 cautelas.

**Por que Wilson.** Com poucas observações, a taxa engana: 1 atraso em 2 dá 50%. O intervalo de Wilson é largo com poucos dados e estreito com muitos. Ao contrário do intervalo "normal", ele não sai de [0, 1] e não colapsa em 0 ou 100% (testado com 0/10, 5/10 e 10/10).

**Medido contra o gabarito.** Método ingênuo (acima da média geral): 11 pessoas apontadas, 5 delas **pontuais da Manutenção**, que seriam cobradas por um problema de processo. Método ajustado: 6 apontadas, os **4 reincidentes plantados** (todos, sem saber quem eram) e 2 ocasionais, que de fato atrasam acima do esperado. Nenhuma pontual.

**Cautela reconstruída, não armazenada.** A view `analise.vw_cautela` pareia cada retirada com a movimentação seguinte (`LEAD`), depois de tirar os pares estorno/estornada da sequência. Custa 13 ms para 5.994 cautelas (o anti-join dos estornos usa o índice único de `estorno_de_id`), por isso não foi materializada.

## D17. Ponto de reposição: demanda censurada e prazo real

**Decisão.** O ponto de reposição de cada material é calculado só pelo histórico: `d*L + z*raiz(L*var_d + d^2*var_L)`, com a demanda (*d*, var_d) medida **só nos dias em que havia estoque no início do dia** e o prazo (*L*, var_L) medido compra a compra, pela data do pedido registrada na entrada.

**Por que excluir os dias sem estoque.** A demanda observada é censurada: sem estoque, a saída é zero porque não havia o que entregar. Incluir esses dias subestima justamente os itens que mais faltam: o cartucho parecia ter demanda 21% menor do que tem.

**Limiares e validação.** Mínimo < 60% do ponto de reposição = mal calibrado; prazo > 1,5x o típico (com 3 compras ou mais) = fornecedor lento; acima do máximo em 70% dos dias = excesso. Acertou os 24 materiais no conjunto padrão e em quatro sementes fora da amostra, com margem folgada (bem calibrados >= 0,84; mal calibrados <= 0,23).

**Bug que a análise revelou na carga.** A view de prazo voltou vazia: a carga não repassava a observação das entradas (onde está a data do pedido). Corrigido, com um teste de fidelidade campo a campo entre o CSV e o banco, comprovado nos dois sentidos (falha sem a correção, passa com ela).

## D18. Power BI com menor privilégio

**Decisão.** O Power BI conecta com um usuário só de leitura (`almox_bi`, membro do grupo `almox_leitura`), e não com o dono do banco. O grupo lê os schemas `bi` (modelo estrela: dimensões de calendário, material, pessoa e setor; fatos de movimentação, cautela e consumo diário), `analise` e `dq`. Não lê `core` nem `staging` e não grava nada (testado: 11 tentativas recusadas com 42501).

**A armadilha que apareceu.** Views rodam com os direitos do dono, mas as funções chamadas dentro delas rodam com os de quem consulta. `analise.momento_referencia()` falhou para o BI. Solução: ela passou a `SECURITY DEFINER` com `search_path` fixo (devolve um único número), e só `core.data_local()` (conta de fuso) foi liberada ao grupo. De quebra, o `EXECUTE` padrão do PUBLIC foi retirado de todas as funções do `core`, inclusive das futuras: as funções de escrita ficam só com o dono.

**Caso-limite.** Sem nenhuma movimentação, a data de referência era NULL e todas as views com período ficavam vazias sem explicação. Agora é "última movimentação ou agora".

## D19. Banco próprio para a aplicação (revista na D27: o Power BI operacional lê este banco)

**Decisão.** A tela do equipamentista usa o banco `almoxarifado_app`, carregado com os mesmos dados fictícios (`python -m almox.carga --recriar --banco app`), e não o banco das análises.

**Por quê.** As análises usam como referência o instante da última movimentação (31/08/2026). Uma retirada feita hoje pela tela mudaria essa referência, o calendário do Power BI e os números dos notebooks (as 5.994 cautelas, os 56 dias sem toner). O banco das análises fica congelado e reproduzível; o da aplicação é o "sistema vivo". A configuração recusa um banco da aplicação com o mesmo nome do banco das análises ou do de testes, e o usuário da API nem tem permissão de conectar no banco das análises (testado).

## D20. Escrita só pelas funções de regra (`SECURITY DEFINER`)

**Decisão.** O usuário da API (grupo `almox_aplicacao`) não tem `INSERT`, `UPDATE` nem `DELETE` em nenhuma tabela do `core`. Ele executa só as duas funções que a tela usa (retirada e devolução), que passaram a `SECURITY DEFINER`: rodam com os direitos do dono do banco.

**Por quê.** Com direitos de tabela, uma falha na API (injeção de SQL, rota esquecida, bug) poderia gravar direto no histórico e pular as regras. Assim, o único caminho para o histórico é a função, que confere perfil, trava a linha e valida a regra. O teste varre todas as tabelas do `core` (inclusive as futuras) e tenta 20 operações proibidas; duas mutações (tirar o `SECURITY DEFINER`; conceder um `INSERT` direto) são detectadas.

**O cuidado que `SECURITY DEFINER` exige.** Uma função que roda como o dono pode ser desviada se resolver nomes pelo `search_path` de quem chama (a pessoa cria um objeto com o mesmo nome num schema seu). Por isso o `search_path` é fixo (`pg_catalog, pg_temp`) e as funções só usam nomes qualificados (`core.xxx`), o que foi conferido antes da mudança e é testado.

**Limitação conhecida.** O banco confia no `p_executado_por` que a API envia (vem da sessão, nunca do corpo do pedido, e isso é testado). Com uma conexão compartilhada, o banco não tem como saber qual pessoa está do outro lado; quem autentica é a API. **Resolvida na D24:** as funções da aplicação passaram a receber o hash do token da sessão.

## D21. Login e sessão sem biblioteca externa

**Decisão.** Senha com `scrypt` do módulo `crypto` do Node (N=2^17, r=8, p=1: parâmetros mínimos da OWASP), comparação em tempo constante e o mesmo tempo de resposta para login inexistente, senão o tempo revelaria quais logins existem (medido: cerca de 0,31 s nos dois casos; a primeira versão gerava o hash fictício na hora e o primeiro login inexistente levava 0,62 s, o que foi corrigido com um hash fixo). Sessão com token aleatório de 32 bytes em cookie `HttpOnly` e `SameSite=Strict`; o banco guarda só o SHA-256 do token. Limite de 5 falhas por login (e 20 por IP) em 15 minutos.

**Por quê sem biblioteca.** O que se precisa (hash lento, token aleatório, cookie) já existe no Node, e cada dependência é código de terceiro rodando com acesso ao banco. `express` e `pg` são as únicas dependências de produção.

**Contra CSRF**, três camadas: o cookie `SameSite=Strict`, a exigência de `Content-Type: application/json` (um formulário de outro site não consegue enviar isso sem o navegador pedir permissão) e a conferência do cabeçalho `Origin`. **Contra XSS**, duas: a tela nunca monta HTML com dados (só `textContent`) e a CSP não permite script inline.

**Limitações conhecidas.** O limite de tentativas fica na memória de um processo (com várias instâncias, teria de ir para o banco ou um Redis). O cookie só ganha o atributo `Secure` com `ALMOX_API_COOKIE_SEGURO=sim`, que exige HTTPS; em `localhost` fica desligado.

## D22. Tela em HTML, CSS e JavaScript puro

**Decisão.** A tela é servida pela própria API (mesma origem, sem CORS), sem framework nem etapa de build, mobile-first. Verde é a cor de identidade; vermelho e âmbar ficam reservados para "vencida" e "vence logo", sempre acompanhados de texto.

**Por quê.** São quatro telas simples. React entra nos projetos 4 e 5, onde a interface justifica. Aqui o aprendizado novo é segurança (D20, D21), e trocar de framework ao mesmo tempo diluiria o foco.

**Verificação.** O fluxo completo (entrar, filtrar, retirar, devolver com avaria, sair, perfil de consulta, tema escuro, largura de celular e de desktop) foi percorrido num navegador real (Playwright, Chromium headless, 390×844), sem erros de console além do 401 esperado da senha errada. A verificação encontrou dois defeitos, corrigidos: a pergunta "quem sou eu?" respondia 401 a cada visita (agora `usuario: null`) e, no Express 5, o callback do `listen` recebe o erro de porta ocupada, que era ignorado (o servidor anunciava "no ar" e saía em silêncio).

## D23. Catálogo militar, militares novos e um mês de uso, só no banco da aplicação

**Contexto.** O sistema precisava de material operacional (controle de distúrbios, formatura e cerimonial, paraquedismo, campanha, EPI, comunicação), de militares identificados por posto e nome de guerra e de movimento suficiente para as telas e o relatório operacional fazerem sentido.

**Decisão.** Posto/graduação e nome de guerra entram no `core` (migração 0013), nos dois bancos; o gerador os sorteia com um gerador aleatório próprio, e os eventos ficam idênticos (testado: só o hash de `pessoas.csv` muda). O catálogo militar (76 materiais patrimoniais com 1.711 unidades e 4 de consumo), 24 militares apresentados em 01/09/2026 e a atividade de setembro (serviço de dia, treino de choque, desfile de 7 de Setembro, salto, campanha, EPI, manutenção e reposição) entram **só no banco da aplicação** (`almox.complemento` e `almox.atividade`).

**Por quê.** O banco das análises continua congelado em 31/08/2026: notebooks, gabarito e números do README não mudam. A atividade é planejada em Python puro com semente fixa (testável sem banco, sempre o mesmo plano) e executada pelas mesmas funções de regra que a tela usa; recarregar o banco reproduz os mesmos números (418 retiradas, 410 devoluções, 25 avarias).

**Postos.** A lista é a pedida pelo dono do projeto (S2, S1, CB, SGT, ST, TEN, CAP, MAJ, TEN-CEL, CEL), com siglas genéricas. "ST" e "SUBTEN" vieram os dois na lista e são o mesmo posto (subtenente); ficou "ST".

**Sem armamento de fogo nem munição.** Tonfa, espadim e sabre entram a pedido, como material de controle de distúrbios e de cerimonial.

## D24. O banco descobre quem está logado (funções `app.*` com o token da sessão)

**Contexto.** A D20 registrava uma limitação: o banco confiava no `p_executado_por` que a API enviava. Com funções que criam usuários, trocam perfil e definem senha, isso deixa de bastar: com uma injeção de SQL na API, alguém chamaria a função passando o id de um administrador.

**Decisão.** O usuário do banco da API executa **só** funções do schema `app` (retirar, devolver, entrada, cadastros, usuários, senha...). Cada uma recebe o **hash SHA-256 do token** da sessão, e `app._usuario()` descobre no banco quem está logado (sessão existente, não vencida, usuário ativo; senão ALM13 → 401). As funções do `core` continuam existindo para a carga e para o dono do banco, mas a API não as executa mais.

**Por quê.** Sem o token de uma sessão válida de administrador, nenhuma função de administrador roda, nem por SQL direto (testado: sessão inexistente, vencida e de usuário inativo; equipamentista tentando se promover). O teste lista exatamente quais funções são `SECURITY DEFINER` e quais a API executa: uma função nova precisa entrar na lista de propósito.

**Custo.** Uma função de embrulho por operação (19). São curtas (uma linha de SQL cada), e o padrão é sempre o mesmo.

## D25. Quantidade sem perder o BMP

**Contexto.** O balcão pede "3 escudos", não "os BMPs 6100001, 6100002 e 6100003". Mas a rastreabilidade (quem está com qual unidade) é o que dá valor ao controle.

**Decisão.** O material patrimonial continua rastreado por unidade. `core.registrar_retirada_lote` escolhe N unidades disponíveis com `FOR UPDATE SKIP LOCKED` (ou usa as que o equipamentista leu pelo BMP) e passa **cada uma** pela função de retirada que já existia. As unidades do mesmo atendimento ficam ligadas por um **código de operação** (`uuid`); a API gera um código por atendimento, para que vários materiais saiam juntos numa transação (se faltar um item, nada sai). A retirada ganhou o estado de saída (BOM ou REGULAR, este com observação) e a devolução em lote trava as unidades sempre na mesma ordem (id crescente), o que evita deadlock.

**Por quê `SKIP LOCKED`.** Com `FOR UPDATE` simples, o segundo balcão esperaria o primeiro terminar e depois poderia achar menos unidades do que pediu. Com `SKIP LOCKED` ele pula as que estão sendo retiradas e pega as livres na hora. Testado com duas conexões (o segundo recebe a resposta sem esperar e nunca a mesma unidade) e com oito simultâneas (nenhuma unidade sai duas vezes, e o estoque não diverge do histórico).

**Caso-limite encontrado.** Se dois atendimentos travam unidades e um desiste, o outro pode receber "estoque insuficiente" com unidades livres. A mensagem distingue os casos ("parte das unidades está sendo retirada em outro atendimento agora; tente de novo") em vez de dizer "5 disponíveis, pedido 3".

**Alternativa descartada.** Um terceiro tipo de controle ("por quantidade, mas devolvível"), sem BMP: mudaria as CHECKs do histórico, as funções e as análises, e perderia exatamente a informação de qual unidade está com quem.

## D26. Administração com auditoria e travas contra se trancar para fora

**Decisão.** Cadastros pela aplicação (categoria, subcategoria, material, militar, usuário, perfil, senha) passam por funções que validam e devolvem mensagens claras (ALM10 parâmetro, ALM11 duplicado) e gravam `core.auditoria`, que, como o histórico, só aceita INSERT. Ninguém tira o próprio acesso de administrador; sempre sobra um administrador ativo (com a trava de todos os administradores, duas alterações simultâneas não deixam o sistema sem nenhum); um militar com material em posse não sai da unidade; mudar o perfil ou desativar um usuário derruba as sessões dele na hora.

**Por quê.** As movimentações já são a auditoria do estoque (D2); faltava a dos cadastros e acessos. As travas existem porque o erro mais caro de uma tela de usuários é o administrador remover o próprio acesso, ou um militar ser transferido levando material.

## D27. Power BI operacional no banco da aplicação (revisão da D19)

**Contexto.** A D19 dizia que o Power BI não conectava no banco da aplicação. As análises pedidas agora (entradas e saídas, posse, mais movimentados, por militar, por equipamentista, manutenção) são operacionais: o lugar delas é o "sistema vivo".

**Decisão.** O grupo de leitura do BI passa a conectar também no `almoxarifado_app`. Lá ele lê só os schemas `bi`, `analise` e `dq`: nem o `core`, nem a auditoria, nem as senhas e sessões do `app` (testado). A migração 0016 cria `dim_operador`, `fato_posse_atual`, `fato_estoque_atual` e `fato_unidade_atual` (fotografias de agora, cada uma com um grão), acrescenta operação, estados, finalidade e hora ao fato de movimentação, e faz o calendário começar na primeira retirada (no banco da aplicação a referência anda com o uso, e o primeiro mês ficava sem data). O guia tem a Parte A (operacional) e a Parte B (analítico, o que já existia).

**O que continua da D19.** Os números das análises e dos notebooks seguem no banco congelado; a aplicação continua sem conectar nele.

## D28. Tela reorganizada em módulos, ainda sem framework

**Decisão.** A tela virou um sistema de gestão: menu lateral por perfil (barra inferior e menu no celular), roteador por hash e uma página por módulo ES (`web/js/paginas/`), com componentes compartilhados em `ui.js` (tabela que vira cartão no celular, diálogo nativo, painel lateral, avisos, esqueleto de carregamento). Continua sem framework e sem etapa de build, com a mesma CSP e a mesma regra contra XSS (nenhum dado vira HTML). **Sem gráficos**, a pedido: a tela é para operar; a análise fica no Power BI.

**Por quê sem React.** O argumento da D22 continua: React entra nos projetos 4 e 5. Aqui as páginas são formulários, tabelas e listas, que o DOM resolve bem com uma função `el()` de 20 linhas, e não há etapa de build para manter.

**Verificação.** Os fluxos de balcão (retirada com dois materiais por quantidade e um por BMP, devolução avariada, painel do estoque, ciclo) e de administração (categoria, subcategoria duplicada, material com `<img onerror>` no nome, entrada de unidades, militar, usuário, troca de perfil derrubando a sessão do outro) foram percorridos no Chromium em 1440×900 e 390×844, sem erro de console além das respostas 4xx provocadas de propósito. A verificação encontrou e corrigiu: contagem de vencidas diferente entre o menu (unidades) e a página (atendimentos), botões empilhando nas tabelas, campo de formulário esticado pelo vizinho e a sombra do link "pular para o conteúdo" aparecendo no topo.
