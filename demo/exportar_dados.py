"""Exporta um retrato do banco da aplicação para a demo que roda no navegador.

A demo (demo/demo-api.js) responde às chamadas /api no próprio navegador, a partir deste
retrato: cadastros, unidades, saldos e as movimentações recentes (as dos últimos dias e as
retiradas que abriram as posses atuais). Nada de senha ou sessão sai daqui: só dados
fictícios que a tela já mostra.

Uso (com o banco da aplicação carregado):
    python demo/exportar_dados.py        -> demo/dados-demo.json
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from almox.banco import conectar
from almox.config import carregar_config_banco

SAIDA = Path(__file__).with_name("dados-demo.json")

CONSULTAS: dict[str, str] = {
    "postos": "SELECT sigla, nome, circulo, ordem FROM core.posto_graduacao ORDER BY ordem",
    "setores": "SELECT id, sigla, nome FROM core.setor ORDER BY sigla",
    "locais": "SELECT id, nome FROM core.local_armazenagem ORDER BY nome",
    "categorias": "SELECT id, nome FROM core.categoria ORDER BY id",
    "subcategorias": "SELECT id, categoria_id, nome FROM core.subcategoria ORDER BY id",
    "pessoas": """
        SELECT id, matricula, nome, nome_guerra, posto_graduacao AS posto, setor_id,
               data_entrada, data_saida
        FROM core.pessoa ORDER BY id""",
    "usuarios": "SELECT id, login, perfil, ativo, pessoa_id FROM core.usuario ORDER BY id",
    "materiais": """
        SELECT m.id, m.codigo, m.nome, m.descricao, m.controle, m.unidade_medida,
               m.prazo_devolucao_horas, m.custo_unitario, m.ativo, m.subcategoria_id,
               m.estoque_minimo, sc.quantidade AS saldo, sc.estoque_minimo AS minimo_consumo,
               sc.estoque_maximo, sc.local_id
        FROM core.material_tipo m
        LEFT JOIN core.saldo_consumo sc ON sc.material_tipo_id = m.id
        ORDER BY m.id""",
    "unidades": """
        SELECT id, material_tipo_id, bmp, numero_serie, status, local_id, detentor_id
        FROM core.unidade_patrimonial ORDER BY id""",
    # As movimentações recentes e as retiradas que abriram cada posse atual (mesmo antigas).
    "movimentacoes": """
        SELECT m.id, m.ocorrida_em, m.tipo, m.material_tipo_id, m.unidade_id, m.pessoa_id,
               m.executado_por, m.variacao, m.status_anterior, m.status_novo,
               m.estado_retirada, m.estado_devolucao, m.observacao, m.finalidade,
               m.documento_ref, m.prazo_devolucao, m.operacao::text AS operacao
        FROM core.movimentacao m
        WHERE m.ocorrida_em >= now() - interval '45 days'
           OR m.id IN (SELECT retirada_id FROM core.vw_posse)
        ORDER BY m.ocorrida_em, m.id""",
}


def _json(valor: Any) -> Any:
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    raise TypeError(f"tipo não serializável: {type(valor)!r}")


def main() -> None:
    config = carregar_config_banco().do_banco_da_aplicacao()
    dados: dict[str, Any] = {}
    with conectar(config) as con:
        # O "agora" do retrato é o último atendimento simulado, e não a hora em que o
        # exportador roda: a simulação termina em 01/10, e um retrato tirado dias depois
        # mostraria vencido tudo o que, na história, ainda está no prazo.
        agora = con.execute("SELECT max(ocorrida_em) FROM core.movimentacao").fetchone()
        if agora is None or agora[0] is None:
            raise RuntimeError("O banco da aplicação não tem movimentações.")
        dados["gerado_em"] = agora[0]
        for nome, consulta in CONSULTAS.items():
            cursor = con.execute(consulta)
            colunas = [c.name for c in cursor.description or []]
            dados[nome] = [dict(zip(colunas, linha, strict=True)) for linha in cursor]
    texto = json.dumps(dados, default=_json, ensure_ascii=False, separators=(",", ":"))
    SAIDA.write_text(texto, encoding="utf-8", newline="\n")
    resumo = ", ".join(f"{k}: {len(v)}" for k, v in dados.items() if isinstance(v, list))
    print(f"{SAIDA.name} ({len(texto) / 1024:.0f} KB) -> {resumo}")


if __name__ == "__main__":
    main()
