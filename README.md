# Controle de Materiais e Cautela — análise de dados de uma unidade logística (dados fictícios)

> **Status: em planejamento.** Projeto 2 do meu portfólio de Dados, na sequência do [Painel de Vendas](https://github.com/DiegoSantiago1/analise-vendas-concessionaria). O plano completo está em [docs/PLAN.md](docs/PLAN.md).

Análise do controle de materiais de uma unidade logística fictícia: carga patrimonial, cautela (quem está com cada material), devoluções, uso dos equipamentos e estoque de consumo.

## Contexto

Trabalhei na Força Aérea Brasileira em funções administrativas, incluindo controle de materiais, estoque e conferência de carga patrimonial. Este projeto transforma essa rotina em um problema de análise de dados.

O sistema e **todos os dados são 100% fictícios**, gerados em Python. Nenhuma informação real (pessoas, unidades, locais, números de patrimônio) entra neste repositório, e o projeto não inclui armamento nem material de armaria.

## Perguntas de negócio

1. **Conferência da carga:** onde a planilha de carga não bate (nomes inconsistentes, números duplicados, itens sem patrimônio, itens não localizados) e onde os erros se concentram?
2. **Cautela e atrasos:** quem está com cada material, há quanto tempo, e quais devoluções estão atrasadas?
3. **Uso e ociosidade:** quais equipamentos são muito usados, quais ficam parados, o que sobra e o que falta?
4. **Consumo e ruptura:** quais itens de consumo vão acabar e quais têm o estoque mínimo mal definido?

## Análises

| # | Pergunta | Onde | Situação |
|---|---|---|---|
| A1 | Conferência da carga | [notebook](notebooks/01_conferencia.ipynb) · [view SQL](db/migracoes/versions/0006_analise_conferencia.py) | Concluída |
| A2 | Cautela e atrasos | — | Próxima |
| A3 | Uso e ociosidade | — | Planejada |
| A4 | Consumo e ruptura | — | Planejada |

**A1 em uma frase:** 47,8% das 358 linhas da planilha de carga têm algum problema, mas 146 delas são só de forma e se resolvem automaticamente; 24 vão para verificação humana, e o Depósito Central concentra 43,9% dos problemas com 15,5% das linhas. A conferência (SQL com `pg_trgm` e Levenshtein) acertou 100% dos erros do conjunto padrão e errou 2 de ~2.900 em sete conjuntos que nunca tinha visto.

Os notebooks são salvos já executados. Para reexecutar: `jupyter nbconvert --to notebook --execute --inplace notebooks/01_conferencia.ipynb` (com o banco carregado).

## Tecnologias previstas

`PostgreSQL` · `SQL` (CTEs e window functions) · `Python` (`Pandas`, `NumPy`) · `Power BI` · `Docker`

## Como rodar

Requisitos: Python 3.14, Docker Desktop e um container PostgreSQL 16 rodando. Este projeto usa o mesmo container do [Painel de Vendas](https://github.com/DiegoSantiago1/analise-vendas-concessionaria) (`docker compose up -d` na pasta dele), com banco e usuário próprios.

```bash
# 1. Ambiente Python
python -m venv .venv
.venv\Scripts\activate            # Windows (no Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt

# 2. Configuração: copie o modelo e troque a senha
copy .env.example .env            # Linux/macOS: cp .env.example .env

# 3. Cria o usuário e o banco do projeto no container (pode rodar de novo sem problema)
python -m almox.bootstrap

# 4. Aplica as migrações
alembic upgrade head

# 5. Gera os dados fictícios (semente 42, 12 meses até 31/08/2026) em data/gerado/
python -m almox.gerador

# 6. Carrega no banco, passando cada evento pelas funções de regra (~1 min).
#    --recriar é obrigatório: apaga e recria o schema (o histórico é imutável).
python -m almox.carga --recriar
```

**Reprodutibilidade:** com a mesma semente e a mesma data final, o gerador produz arquivos byte a byte idênticos. O [manifesto](data/gerado/manifesto.json) (versionado) guarda o SHA-256 de cada arquivo: depois do passo 5, compare os seus hashes com os dele.

**Atenção:** como o banco fica no container do outro projeto, um `docker compose down -v` lá apaga também este banco (o `-v` remove o volume). Para recriar, repita os passos 3 a 6.

### Qualidade

```bash
ruff format --check .             # formatação
ruff check .                      # lint (inclui regras de segurança)
mypy                              # verificação de tipos (modo strict)
pytest                            # todos os testes (precisa do banco; ~70 s)
pytest -m "not lento"             # sem a carga completa (~15 s)
pytest -m "not integracao"        # só os testes que não usam o banco
```

## Próximos passos

1. ~~Criar o banco, o schema com as regras de integridade e o gerador de dados com padrões documentados.~~ Feito (Fase 1).
2. Fazer as análises em SQL e Pandas, uma pergunta por vez.
3. Checagens automáticas de qualidade de dados.
4. Montar o relatório no Power BI e escrever o README de case com os insights.
