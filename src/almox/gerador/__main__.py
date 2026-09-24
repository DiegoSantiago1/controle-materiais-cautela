"""Gera o conjunto de dados sintéticos em CSV.

Uso:
    python -m almox.gerador                     # semente 42, até 2026-08-31, em data/gerado
    python -m almox.gerador --semente 7 --ate 2026-06-30 --saida outra/pasta
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from almox.config import RAIZ_PROJETO
from almox.gerador import catalogo as cat
from almox.gerador.planilha import gerar_planilha
from almox.gerador.saida import gravar
from almox.gerador.simulacao import gerar


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--semente", type=int, default=cat.SEMENTE_PADRAO)
    parser.add_argument("--ate", default=cat.ANCORA_PADRAO, help="último dia (AAAA-MM-DD)")
    parser.add_argument("--saida", type=Path, default=RAIZ_PROJETO / "data" / "gerado")
    args = parser.parse_args(argumentos)

    try:
        ancora = date.fromisoformat(args.ate)
    except ValueError:
        parser.error(f"--ate inválido: {args.ate!r} (use AAAA-MM-DD)")
    if ancora >= date.today():
        parser.error("--ate precisa ser uma data passada: o banco recusa movimentações futuras")

    dataset = gerar(args.semente, ancora.isoformat())
    manifesto = gravar(dataset, gerar_planilha(dataset), args.saida)
    print(f"Gerado em {args.saida} (semente {args.semente}, {dataset.inicio} a {dataset.fim}):")
    for chave, valor in manifesto["contagens"].items():  # type: ignore[attr-defined]
        print(f"  {chave}: {valor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
