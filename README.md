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
```

**Atenção:** como o banco fica no container do outro projeto, um `docker compose down -v` lá apaga também este banco (o `-v` remove o volume). Para recriar, repita os passos 3 e 4.

### Qualidade

```bash
ruff format --check .             # formatação
ruff check .                      # lint (inclui regras de segurança)
mypy                              # verificação de tipos (modo strict)
pytest                            # todos os testes (precisa do banco)
pytest -m "not integracao"        # só os testes que não usam o banco
```

## Próximos passos

1. Criar o schema com as regras de integridade (o banco, o usuário e as migrações já estão configurados).
2. Gerar o dataset sintético com padrões documentados.
3. Fazer as análises em SQL e Pandas, uma pergunta por vez.
4. Montar o relatório no Power BI e escrever o README de case com os insights.
