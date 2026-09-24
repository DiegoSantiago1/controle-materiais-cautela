"""Grava o conjunto gerado em CSV (chaves naturais, legíveis) e um manifesto com hashes.

O manifesto guarda o SHA-256 de cada arquivo: rodar o gerador de novo com a mesma
semente e a mesma data-âncora tem de produzir exatamente os mesmos hashes. É assim que
a afirmação "o gerador é reproduzível" é conferida, e não só declarada.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path

from almox.gerador import catalogo as cat
from almox.gerador.planilha import Linha
from almox.gerador.simulacao import Dataset

ARQUIVOS_DADOS = [
    "setores.csv",
    "locais.csv",
    "categorias.csv",
    "materiais.csv",
    "pessoas.csv",
    "usuarios.csv",
    "saldos.csv",
    "eventos.csv",
    "planilha_carga.csv",
    "gabarito_linha.csv",
    "gabarito_erro.csv",
    "gabarito_padroes.json",
]


def _texto(valor: object) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, float):
        return f"{valor:.2f}"
    return str(valor)


def _gravar_csv(
    caminho: Path, cabecalho: Sequence[str], linhas: Iterable[Sequence[object]]
) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, lineterminator="\n")
        escritor.writerow(cabecalho)
        for linha in linhas:
            escritor.writerow([_texto(v) for v in linha])


def _subcategoria_para_categoria() -> dict[str, str]:
    return {sub: categoria for categoria, subs in cat.CATEGORIAS.items() for sub in subs}


def gravar(dataset: Dataset, planilha: list[Linha], pasta: Path) -> dict[str, object]:
    """Grava todos os arquivos em `pasta` e devolve o manifesto (também gravado)."""
    pasta.mkdir(parents=True, exist_ok=True)
    categoria_de = _subcategoria_para_categoria()

    _gravar_csv(pasta / "setores.csv", ["sigla", "nome"], cat.SETORES.items())
    _gravar_csv(pasta / "locais.csv", ["nome"], [[nome] for nome in cat.LOCAIS])
    _gravar_csv(
        pasta / "categorias.csv",
        ["categoria", "subcategoria"],
        [(c, s) for c, subs in cat.CATEGORIAS.items() for s in subs],
    )
    materiais: list[Sequence[object]] = []
    for t in cat.SERIAIS:
        sub = t.subcategoria
        materiais.append(
            (t.codigo, t.nome, categoria_de[sub], sub, "UN", "SERIAL", t.prazo_h, t.custo)
        )
    for c in cat.CONSUMOS:
        sub = c.subcategoria
        materiais.append(
            (c.codigo, c.nome, categoria_de[sub], sub, c.unidade, "CONSUMO", None, c.custo)
        )
    _gravar_csv(
        pasta / "materiais.csv",
        [
            "codigo",
            "nome",
            "categoria",
            "subcategoria",
            "unidade_medida",
            "controle",
            "prazo_devolucao_horas",
            "custo_unitario",
        ],
        materiais,
    )
    _gravar_csv(
        pasta / "pessoas.csv",
        ["matricula", "nome", "setor", "data_entrada", "data_saida"],
        [(p.matricula, p.nome, p.setor, p.data_entrada, p.data_saida) for p in dataset.pessoas],
    )
    _gravar_csv(
        pasta / "usuarios.csv",
        ["login", "matricula", "perfil"],
        [(u.login, u.matricula, u.perfil) for u in dataset.usuarios],
    )
    _gravar_csv(
        pasta / "saldos.csv",
        ["codigo", "local", "estoque_minimo", "estoque_maximo"],
        [(s.codigo, s.local, s.minimo, s.maximo) for s in dataset.saldos],
    )
    _gravar_csv(
        pasta / "eventos.csv",
        [
            "seq",
            "ocorrida_em",
            "operacao",
            "usuario",
            "material",
            "unidade",
            "pessoa",
            "quantidade",
            "estado",
            "novo_status",
            "bmp",
            "numero_serie",
            "local",
            "setor_destino",
            "documento",
            "observacao",
            "estorno_de",
        ],
        [
            (
                e.seq,
                e.ocorrida_em,
                e.operacao,
                e.usuario,
                e.material,
                e.unidade,
                e.pessoa,
                e.quantidade,
                e.estado,
                e.novo_status,
                e.bmp,
                e.numero_serie,
                e.local,
                e.setor_destino,
                e.documento,
                e.observacao,
                e.estorno_de,
            )
            for e in dataset.eventos
        ],
    )
    _gravar_csv(
        pasta / "planilha_carga.csv",
        ["linha", "bmp", "nomenclatura", "numero_serie", "local", "situacao", "observacao"],
        [
            (i + 1, x.bmp, x.nomenclatura, x.numero_serie, x.local, x.situacao, x.observacao)
            for i, x in enumerate(planilha)
        ],
    )
    unidades = {u.ref: u for u in dataset.unidades}
    _gravar_csv(
        pasta / "gabarito_linha.csv",
        ["linha", "unidade_ref", "bmp_correto", "material_codigo", "local_correto", "duplicata_de"],
        [
            (
                i + 1,
                x.unidade_ref,
                unidades[x.unidade_ref].bmp,
                x.material,
                x.local_correto,
                None if x.duplicata_de is None else x.duplicata_de + 1,
            )
            for i, x in enumerate(planilha)
        ],
    )
    _gravar_csv(
        pasta / "gabarito_erro.csv",
        ["linha", "padrao", "tipo_erro", "campo", "valor_na_planilha", "valor_correto"],
        [(i + 1, *erro) for i, x in enumerate(planilha) for erro in x.erros],
    )
    verdade = {
        "aviso": "Verdade conhecida só pelo gerador. As análises não devem usá-la para "
        "chegar às conclusões; serve para conferir, no fim, se acertaram.",
        "perfil_pontualidade": {p.matricula: p.perfil for p in dataset.pessoas},
        "calibracao_consumo": {c.codigo: c.calibracao for c in cat.CONSUMOS},
        "dias_de_pico": [d.isoformat() for d in dataset.dias_de_pico],
        "demanda_nao_atendida": [[d.isoformat(), c, q] for d, c, q in dataset.demanda_nao_atendida],
        "unidades_que_circulam": sorted(u.ref for u in dataset.unidades if u.peso > 0),
    }
    (pasta / "gabarito_padroes.json").write_text(
        json.dumps(verdade, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    manifesto: dict[str, object] = {
        "semente": dataset.semente,
        "inicio": dataset.inicio.isoformat(),
        "ancora": dataset.fim.isoformat(),
        "contagens": {
            "pessoas": len(dataset.pessoas),
            "unidades": len(dataset.unidades),
            "tipos_de_material": len(materiais),
            "eventos": len(dataset.eventos),
            "eventos_por_operacao": dict(
                sorted(Counter(e.operacao for e in dataset.eventos).items())
            ),
            "linhas_planilha": len(planilha),
            "erros_injetados": sum(len(x.erros) for x in planilha),
        },
        "sha256": {nome: _sha256(pasta / nome) for nome in ARQUIVOS_DADOS},
    }
    (pasta / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    return manifesto


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()
