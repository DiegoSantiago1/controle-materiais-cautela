# Guia do relatório Power BI

O banco já entrega os dados prontos para o Power BI no schema `bi` (modelo estrela) e nas views de análise. Este guia mostra como conectar, montar o modelo e as medidas, e sugere as páginas do relatório, uma por pergunta de negócio.

## 1. Conexão (somente leitura)

O Power BI conecta com um usuário **que só lê**: o `almox_bi` (nome e senha no `.env`, variáveis `ALMOX_BI_USER` e `ALMOX_BI_PASSWORD`). Ele enxerga os schemas `bi`, `analise` e `dq`. **Não** enxerga as tabelas do `core` nem o `staging`, e não consegue gravar nada: isso é testado em `tests/test_bi.py`.

No Power BI Desktop: **Obter dados → Banco de dados PostgreSQL**.

| Campo | Valor |
|---|---|
| Servidor | `127.0.0.1:5432` |
| Banco de dados | `almoxarifado` |
| Modo | **Importar** (os dados cabem com folga; o relatório fica rápido) |
| Credenciais | Banco de dados → usuário `almox_bi` e a senha do `.env` |

> Se o Power BI pedir, marque a opção para não usar criptografia na conexão local, ou instale o driver Npgsql que ele sugerir. O banco só aceita conexões desta máquina (porta publicada em `127.0.0.1`).

## 2. Tabelas a importar

**Modelo estrela** (schema `bi`):

| Tabela | Tipo | Chave | O que tem |
|---|---|---|---|
| `bi.dim_calendario` | dimensão | `data` | um dia por linha nos 12 meses: ano, mês, trimestre, dia útil |
| `bi.dim_material` | dimensão | `codigo` | catálogo: nome, categoria, subcategoria, controle, custo |
| `bi.dim_pessoa` | dimensão | `matricula` | nome, setor, datas de entrada e saída |
| `bi.dim_setor` | dimensão | `sigla` | nome do setor |
| `bi.fato_movimentacao` | fato | `id` | cada movimentação do histórico (15,7 mil) |
| `bi.fato_cautela` | fato | `retirada_id` | cada cautela: prazo, devolução, atraso |
| `bi.fato_consumo_diario` | fato | `data` + `material` | saída e saldo de cada material de consumo por dia |

**Tabelas de apoio** (já agregadas; úteis para cartões e tabelas):
`analise.vw_uso_material` (A3), `analise.vw_status_consumo` (situação atual), `analise.vw_ruptura` (episódios de falta), `analise.vw_atraso_pessoa` (A2), `analise.vw_conferencia_planilha` (A1), `dq.vw_ultima_execucao` (qualidade de dados).

## 3. Relacionamentos

Em **Exibição de modelo**, ligue as dimensões aos fatos (um para muitos, filtro em direção única, da dimensão para o fato):

| Dimensão (lado 1) | Fato (lado muitos) |
|---|---|
| `dim_calendario[data]` | `fato_movimentacao[data]` |
| `dim_calendario[data]` | `fato_cautela[data_retirada]` |
| `dim_calendario[data]` | `fato_consumo_diario[data]` |
| `dim_material[codigo]` | `fato_movimentacao[material]`, `fato_cautela[material]`, `fato_consumo_diario[material]` |
| `dim_pessoa[matricula]` | `fato_movimentacao[pessoa]`, `fato_cautela[pessoa]` |
| `dim_setor[sigla]` | `dim_pessoa[setor]` |

Marque `dim_calendario` como **tabela de datas** (botão direito → Marcar como tabela de datas → coluna `data`). Sem isso, as funções de inteligência de tempo do DAX não funcionam direito.

**Por que modelo estrela:** cada fato guarda só códigos e números; os textos (nome do material, setor) ficam nas dimensões. O filtro escolhido numa dimensão (um setor, um mês) passa para todos os fatos ligados a ela, e o modelo fica menor e mais rápido.

## 4. Medidas (DAX), com o que cada uma faz

> **Não verificado aqui:** as medidas seguem a sintaxe padrão do DAX, mas não foram executadas (o Power BI não roda no ambiente em que o projeto foi construído). Os dados que elas leem foram testados; confira o resultado de cada medida com os números de referência da seção 5.

Crie uma tabela vazia `Medidas` (Inserir → Inserir dados → OK) para guardar as medidas num só lugar.

```dax
Cautelas = COUNTROWS ( fato_cautela )
```
Conta as linhas da tabela de cautelas **no contexto do filtro** (mês, setor, material...). É a base das outras.

```dax
Cautelas atrasadas = CALCULATE ( [Cautelas], fato_cautela[atrasada] = TRUE () )
```
`CALCULATE` muda o filtro: conta só as linhas com `atrasada` verdadeiro, mantendo os outros filtros da página.

```dax
% de atraso = DIVIDE ( [Cautelas atrasadas], [Cautelas] )
```
`DIVIDE` em vez de `/`: se não houver cautelas no filtro, devolve vazio em vez de erro de divisão por zero.

```dax
Rádios devolvidos no mesmo dia =
DIVIDE (
    CALCULATE ( [Cautelas], fato_cautela[mesmo_dia] = TRUE (),
                dim_material[subcategoria] = "Rádios portáteis" ),
    CALCULATE ( [Cautelas], fato_cautela[situacao] = "DEVOLVIDA",
                dim_material[subcategoria] = "Rádios portáteis" )
)
```
Dois filtros no mesmo `CALCULATE` se combinam com "E". O filtro em `dim_material` chega ao fato pelo relacionamento.

```dax
Dias com falta = CALCULATE ( COUNTROWS ( fato_consumo_diario ), fato_consumo_diario[zerado] = TRUE () )
```
Cada linha do fato de consumo é um material em um dia: contar as linhas zeradas dá "dias com falta".

```dax
Saldo no fim do período =
CALCULATE (
    SUM ( fato_consumo_diario[saldo_fim_do_dia] ),
    LASTDATE ( dim_calendario[data] )
)
```
Saldo **não se soma no tempo** (somar o saldo de 30 dias não faz sentido). `LASTDATE` pega só o último dia do filtro: num gráfico por mês, mostra o saldo do fim de cada mês. Isso é o que se chama de medida semiaditiva.

```dax
Valor parado = SUM ( 'analise vw_uso_material'[valor_parado] )
```
(O nome da tabela depende de como o Power BI a nomear na importação.)

## 5. Páginas sugeridas (uma por pergunta)

| Página | Pergunta | Visuais sugeridos |
|---|---|---|
| Visão geral | Como está o almoxarifado hoje? | cartões: cautelas no ano, % de atraso, itens de consumo críticos (`vw_status_consumo`), ocorrências de qualidade (`dq.vw_ultima_execucao`) |
| A1 Conferência | Onde a planilha não bate? | barras por tipo de problema e por local (`vw_conferencia_planilha`); tabela das divergências com o histórico |
| A2 Cautela e atrasos | Quem atrasa e onde? | % de atraso por subcategoria e setor (matriz); tabela das cautelas vencidas em aberto (`fato_cautela`, `situacao = EM_ABERTO`, `atrasada`) |
| A3 Uso e ociosidade | O que sobra e o que falta? | barras de valor parado e de horas esgotado (`vw_uso_material`); segmentação pela classe ABC |
| A4 Consumo e ruptura | O que vai faltar? | linha do saldo por dia com segmentação de material (`fato_consumo_diario`); tabela de episódios (`vw_ruptura`); status atual |

Os notebooks (`notebooks/0*.ipynb`) têm os números de referência para conferir se o relatório está certo: por exemplo, 5.994 cautelas no ano, 11,8% com atraso e 56 dias sem toner.

## 6. Atualizar

Os dados são fictícios e fixos (semente 42). Se o banco for recarregado (`python -m almox.carga --recriar`), basta **Atualizar** no Power BI. Como o usuário do BI e as permissões são recriados pelo bootstrap e pelas migrações, a conexão continua funcionando.
