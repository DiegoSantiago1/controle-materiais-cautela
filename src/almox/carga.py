"""Carrega o conjunto gerado (data/gerado) no banco, passando pelas funções de regra.

Uso:
    python -m almox.carga --recriar          # banco principal (apaga e recria o schema)

Cada evento é reproduzido pela função do banco correspondente (retirada, devolução,
estorno...). Assim, os dados carregados obedecem às mesmas regras que valerão para a
aplicação; se o gerador tivesse produzido algo proibido, a carga falharia.

Tudo acontece numa transação: ou entra tudo, ou nada. No fim, duas conferências:
a view de divergência (estado x histórico) precisa estar vazia, e o estado final de
cada unidade no banco precisa bater com o que o gerador calculou em Python.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

from almox.banco import Conexao, chamar_funcao, conectar
from almox.config import RAIZ_PROJETO, ConfigBanco, ConfigError, carregar_config_banco
from almox.gerador.planilha import estado_final
from almox.gerador.simulacao import Evento
from almox.migracoes import recriar_schema

PASTA_PADRAO = RAIZ_PROJETO / "data" / "gerado"


class ErroDeCarga(RuntimeError):
    """Falha ao carregar: o evento e o motivo vão na mensagem."""


def _ler(pasta: Path, nome: str) -> Iterator[dict[str, str]]:
    with (pasta / nome).open(encoding="utf-8", newline="") as arquivo:
        yield from csv.DictReader(arquivo)


def _ou_nulo(texto: str) -> str | None:
    return texto if texto != "" else None


def _inserir(con: Conexao, comando: str, valores: list[object]) -> int:
    linha = con.execute(comando, valores).fetchone()
    if linha is None:
        raise ErroDeCarga(f"INSERT não devolveu id: {comando}")
    return int(linha[0])


class Carga:
    def __init__(self, con: Conexao, pasta: Path) -> None:
        self.con = con
        self.pasta = pasta
        self.setor: dict[str, int] = {}
        self.local: dict[str, int] = {}
        self.subcategoria: dict[str, int] = {}
        self.material: dict[str, int] = {}
        self.pessoa: dict[str, int] = {}
        self.usuario: dict[str, int] = {}
        self.unidade: dict[str, int] = {}
        self.movimentacao: dict[int, int] = {}  # seq do evento -> id da movimentação

    # ------------------------------------------------------------ cadastros
    def cadastros(self) -> None:
        c = self.con
        for linha in _ler(self.pasta, "setores.csv"):
            self.setor[linha["sigla"]] = _inserir(
                c,
                "INSERT INTO core.setor (sigla, nome) VALUES (%s, %s) RETURNING id",
                [linha["sigla"], linha["nome"]],
            )
        for linha in _ler(self.pasta, "locais.csv"):
            self.local[linha["nome"]] = _inserir(
                c,
                "INSERT INTO core.local_armazenagem (nome) VALUES (%s) RETURNING id",
                [linha["nome"]],
            )
        categorias: dict[str, int] = {}
        for linha in _ler(self.pasta, "categorias.csv"):
            if linha["categoria"] not in categorias:
                categorias[linha["categoria"]] = _inserir(
                    c,
                    "INSERT INTO core.categoria (nome) VALUES (%s) RETURNING id",
                    [linha["categoria"]],
                )
            self.subcategoria[linha["subcategoria"]] = _inserir(
                c,
                "INSERT INTO core.subcategoria (categoria_id, nome) VALUES (%s, %s) RETURNING id",
                [categorias[linha["categoria"]], linha["subcategoria"]],
            )
        for linha in _ler(self.pasta, "materiais.csv"):
            self.material[linha["codigo"]] = _inserir(
                c,
                "INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, "
                "controle, prazo_devolucao_horas, custo_unitario) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                [
                    linha["codigo"],
                    linha["nome"],
                    self.subcategoria[linha["subcategoria"]],
                    linha["unidade_medida"],
                    linha["controle"],
                    _ou_nulo(linha["prazo_devolucao_horas"]),
                    linha["custo_unitario"],
                ],
            )
        for linha in _ler(self.pasta, "pessoas.csv"):
            self.pessoa[linha["matricula"]] = _inserir(
                c,
                "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, data_saida) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                [
                    linha["matricula"],
                    linha["nome"],
                    self.setor[linha["setor"]],
                    linha["data_entrada"],
                    _ou_nulo(linha["data_saida"]),
                ],
            )
        for linha in _ler(self.pasta, "usuarios.csv"):
            self.usuario[linha["login"]] = _inserir(
                c,
                "INSERT INTO core.usuario (pessoa_id, login, perfil) VALUES (%s, %s, %s) "
                "RETURNING id",
                [self.pessoa[linha["matricula"]], linha["login"], linha["perfil"]],
            )
        administrador = next(
            u for u in _ler(self.pasta, "usuarios.csv") if u["perfil"] == "ADMINISTRADOR"
        )
        for linha in _ler(self.pasta, "saldos.csv"):
            chamar_funcao(
                c,
                "cadastrar_saldo_consumo",
                p_material_tipo_id=self.material[linha["codigo"]],
                p_local_id=self.local[linha["local"]],
                p_estoque_minimo=int(linha["estoque_minimo"]),
                p_estoque_maximo=int(linha["estoque_maximo"]),
                p_executado_por=self.usuario[administrador["login"]],
            )

    # ------------------------------------------------------------ eventos
    def _executar(self, e: dict[str, str]) -> None:
        operacao = e["operacao"]
        comum: dict[str, object] = {
            "p_executado_por": self.usuario[e["usuario"]],
            "p_ocorrida_em": datetime.fromisoformat(e["ocorrida_em"]),
        }
        pessoa = self.pessoa.get(e["pessoa"]) if e["pessoa"] else None
        setor = self.setor.get(e["setor_destino"]) if e["setor_destino"] else None
        c = self.con
        if operacao == "entrada_unidade":
            self.unidade[e["unidade"]] = chamar_funcao(
                c,
                "registrar_entrada_unidade",
                **comum,
                p_material_tipo_id=self.material[e["material"]],
                p_local_id=self.local[e["local"]],
                p_bmp=_ou_nulo(e["bmp"]),
                p_numero_serie=_ou_nulo(e["numero_serie"]),
                p_documento_ref=_ou_nulo(e["documento"]),
                p_observacao=_ou_nulo(e["observacao"]),
            )
            return
        if operacao == "retirada_unidade":
            mov = chamar_funcao(
                c,
                "registrar_retirada_unidade",
                **comum,
                p_unidade_id=self.unidade[e["unidade"]],
                p_pessoa_id=pessoa,
                p_setor_destino_id=setor,
                p_observacao=_ou_nulo(e["observacao"]),
            )
        elif operacao == "devolucao_unidade":
            mov = chamar_funcao(
                c,
                "registrar_devolucao_unidade",
                **comum,
                p_unidade_id=self.unidade[e["unidade"]],
                p_pessoa_id=pessoa,
                p_estado=e["estado"],
                p_observacao=_ou_nulo(e["observacao"]),
            )
        elif operacao == "alterar_status":
            mov = chamar_funcao(
                c,
                "alterar_status_unidade",
                **comum,
                p_unidade_id=self.unidade[e["unidade"]],
                p_novo_status=e["novo_status"],
                p_justificativa=e["observacao"],
                p_bmp=_ou_nulo(e["bmp"]),
            )
        elif operacao == "entrada_consumo":
            mov = chamar_funcao(
                c,
                "registrar_entrada_consumo",
                **comum,
                p_material_tipo_id=self.material[e["material"]],
                p_quantidade=int(e["quantidade"]),
                p_documento_ref=_ou_nulo(e["documento"]),
                p_observacao=_ou_nulo(e["observacao"]),
            )
        elif operacao == "retirada_consumo":
            mov = chamar_funcao(
                c,
                "registrar_retirada_consumo",
                **comum,
                p_material_tipo_id=self.material[e["material"]],
                p_quantidade=int(e["quantidade"]),
                p_pessoa_id=pessoa,
                p_setor_destino_id=setor,
                p_observacao=_ou_nulo(e["observacao"]),
            )
        elif operacao == "ajuste_consumo":
            mov = chamar_funcao(
                c,
                "registrar_ajuste_consumo",
                **comum,
                p_material_tipo_id=self.material[e["material"]],
                p_quantidade_contada=int(e["quantidade"]),
                p_justificativa=e["observacao"],
            )
        elif operacao == "estorno":
            mov = chamar_funcao(
                c,
                "estornar_movimentacao",
                **comum,
                p_movimentacao_id=self.movimentacao[int(e["estorno_de"])],
                p_justificativa=e["observacao"],
            )
        else:
            raise ErroDeCarga(f"operação desconhecida: {operacao!r}")
        if mov is not None:
            self.movimentacao[int(e["seq"])] = int(mov)

    def eventos(self) -> int:
        total = 0
        for evento in _ler(self.pasta, "eventos.csv"):
            try:
                self._executar(evento)
            except psycopg.Error as erro:
                raise ErroDeCarga(
                    f"evento seq={evento['seq']} ({evento['operacao']} em {evento['ocorrida_em']}) "
                    f"recusado pelo banco [{erro.sqlstate}]: {erro}"
                ) from erro
            total += 1
        return total

    # ------------------------------------------------------------ staging
    def _copiar(
        self, arquivo: str, tabela: str, colunas: list[str], fixas: dict[str, str] | None = None
    ) -> int:
        """COPY do CSV para a tabela. Célula vazia vira NULL; `fixas` são colunas com o
        mesmo valor em todas as linhas (ex.: nome do arquivo de origem)."""
        fixas = fixas or {}
        todas = colunas + list(fixas)
        comando = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(*tabela.split(".")), sql.SQL(", ").join(map(sql.Identifier, todas))
        )
        total = 0
        with self.con.cursor().copy(comando) as copia:
            for linha in _ler(self.pasta, arquivo):
                copia.write_row([_ou_nulo(linha[c]) for c in colunas] + list(fixas.values()))
                total += 1
        return total

    def staging(self) -> None:
        self._copiar(
            "planilha_carga.csv",
            "staging.carga_planilha",
            ["linha", "bmp", "nomenclatura", "numero_serie", "local", "situacao", "observacao"],
            fixas={"arquivo": "planilha_carga.csv"},
        )
        self._copiar(
            "gabarito_linha.csv",
            "staging.gabarito_linha",
            [
                "linha",
                "unidade_ref",
                "bmp_correto",
                "material_codigo",
                "local_correto",
                "duplicata_de",
            ],
        )
        self._copiar(
            "gabarito_erro.csv",
            "staging.gabarito_erro",
            ["linha", "padrao", "tipo_erro", "campo", "valor_na_planilha", "valor_correto"],
        )

    # ------------------------------------------------------------ conferências
    def conferir(self) -> None:
        divergencias = self.con.execute("SELECT * FROM core.vw_divergencia_estado").fetchall()
        if divergencias:
            raise ErroDeCarga(f"estado diverge do histórico: {divergencias[:5]}")

        # Estado esperado: reconstruído em Python a partir dos MESMOS eventos carregados.
        esperado = estado_final(eventos_do_csv(self.pasta))
        ref_por_id = {v: k for k, v in self.unidade.items()}
        no_banco = {
            ref_por_id[i]: (status, bmp)
            for i, status, bmp in self.con.execute(
                "SELECT id, status, bmp FROM core.unidade_patrimonial WHERE id = ANY(%s)",
                [list(ref_por_id)],
            )
        }
        diferentes = [ref for ref, e in esperado.items() if no_banco.get(ref) != (e.status, e.bmp)]
        if diferentes:
            raise ErroDeCarga(f"estado final diferente do esperado em {diferentes[:5]}")


def _inteiro_ou_nulo(texto: str) -> int | None:
    return int(texto) if texto != "" else None


def eventos_do_csv(pasta: Path) -> list[Evento]:
    """Lê eventos.csv de volta para objetos Evento (mesma estrutura do gerador)."""
    return [
        Evento(
            ocorrida_em=datetime.fromisoformat(e["ocorrida_em"]),
            operacao=e["operacao"],
            usuario=e["usuario"],
            material=e["material"],
            unidade=_ou_nulo(e["unidade"]),
            pessoa=_ou_nulo(e["pessoa"]),
            quantidade=_inteiro_ou_nulo(e["quantidade"]),
            estado=_ou_nulo(e["estado"]),
            novo_status=_ou_nulo(e["novo_status"]),
            bmp=_ou_nulo(e["bmp"]),
            numero_serie=_ou_nulo(e["numero_serie"]),
            local=_ou_nulo(e["local"]),
            setor_destino=_ou_nulo(e["setor_destino"]),
            documento=_ou_nulo(e["documento"]),
            observacao=_ou_nulo(e["observacao"]),
            estorno_de=_inteiro_ou_nulo(e["estorno_de"]),
            seq=int(e["seq"]),
        )
        for e in _ler(pasta, "eventos.csv")
    ]


def carregar(
    config: ConfigBanco, pasta: Path = PASTA_PADRAO, recriar: bool = True
) -> dict[str, float]:
    """Recria o schema (se pedido) e carrega tudo numa transação. Devolve tempos e contagens."""
    if not (pasta / "manifesto.json").exists():
        raise ErroDeCarga(f"{pasta} não tem manifesto.json: rode 'python -m almox.gerador' antes")
    inicio = time.perf_counter()
    if recriar:
        recriar_schema(config.url())
    with conectar(config) as con:
        carga = Carga(con, pasta)
        carga.cadastros()
        t_eventos = time.perf_counter()
        eventos = carga.eventos()
        t_eventos = time.perf_counter() - t_eventos
        carga.staging()
        carga.conferir()
    return {
        "eventos": eventos,
        "segundos_eventos": t_eventos,
        "segundos_total": time.perf_counter() - inicio,
    }


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carrega data/gerado no banco principal.")
    parser.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    parser.add_argument(
        "--recriar",
        action="store_true",
        help="obrigatório: apaga e recria o schema antes de carregar (o histórico é imutável)",
    )
    args = parser.parse_args(argumentos)
    if not args.recriar:
        parser.error(
            "use --recriar para confirmar: a carga apaga todos os dados do banco principal"
        )
    try:
        config = carregar_config_banco()
        resultado = carregar(config, args.pasta)
    except (ConfigError, ErroDeCarga) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as erro:
        print(
            f"Erro: banco inacessível ({erro}). Docker Desktop aberto? Já rodou "
            "'python -m almox.bootstrap'?",
            file=sys.stderr,
        )
        return 1
    print(
        f"Carga concluída no banco {config.nome!r}: {resultado['eventos']:.0f} eventos em "
        f"{resultado['segundos_eventos']:.1f} s (total {resultado['segundos_total']:.1f} s)."
    )
    print("Conferências: histórico x estado sem divergência; estado final igual ao do gerador.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
