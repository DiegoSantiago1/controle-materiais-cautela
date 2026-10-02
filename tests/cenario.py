"""Cenário de testes: cadastros mínimos e fábricas de materiais.

A base (pessoas, usuários de cada perfil, setores, local) é criada uma vez por execução
e confirmada no banco de testes. Os materiais são criados por teste; dentro da
transação do teste, somem no ROLLBACK.
"""

import itertools
from dataclasses import dataclass
from datetime import date, datetime

from almox.banco import Conexao, chamar_funcao

from .apoio import T0, valor

_sequencia = itertools.count(1)


@dataclass(frozen=True)
class Base:
    subcategoria_serial: int
    subcategoria_consumo: int
    setor: int
    local: int
    pessoa: int
    pessoa2: int
    pessoa_transferida: int  # saiu da unidade em 2025-12-31 (antes de T0)
    pessoa_nova: int  # chega em 2026-06-01 (depois de T0)
    admin: int
    estoquista: int
    equipamentista: int
    consulta: int
    usuario_inativo: int


def _letras(n: int) -> str:
    """Número em letras (A, B, ..., Z, BA, ...): siglas de setor aceitam só letras."""
    texto = ""
    while True:
        n, resto = divmod(n, 26)
        texto = chr(ord("A") + resto) + texto
        if n == 0:
            return texto.rjust(2, "A")


def _inserir(con: Conexao, comando: str, parametros: dict[str, object]) -> int:
    resultado = valor(con, comando, parametros)
    assert isinstance(resultado, int)
    return resultado


def _pessoa(con: Conexao, setor: int, entrada: date, saida: date | None = None) -> int:
    n = next(_sequencia)
    return _inserir(
        con,
        "INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, data_saida, "
        "posto_graduacao, nome_guerra) "
        "VALUES (%(m)s, %(n)s, %(s)s, %(e)s, %(x)s, 'S1', %(g)s) RETURNING id",
        {
            "m": f"{9000000 + n}",
            "n": f"Pessoa Teste {n}",
            "s": setor,
            "e": entrada,
            "x": saida,
            "g": f"Teste {n}",
        },
    )


def _usuario(con: Conexao, pessoa: int, perfil: str, ativo: bool = True) -> int:
    n = next(_sequencia)
    return _inserir(
        con,
        "INSERT INTO core.usuario (pessoa_id, login, perfil, ativo) "
        "VALUES (%(p)s, %(l)s, %(f)s, %(a)s) RETURNING id",
        {"p": pessoa, "l": f"teste.{n}", "f": perfil, "a": ativo},
    )


def criar_base(con: Conexao) -> Base:
    n = next(_sequencia)
    categoria = _inserir(
        con,
        "INSERT INTO core.categoria (nome) VALUES (%(n)s) RETURNING id",
        {"n": f"Categoria Teste {n}"},
    )
    sub_serial, sub_consumo = (
        _inserir(
            con,
            "INSERT INTO core.subcategoria (categoria_id, nome) VALUES (%(c)s, %(n)s) RETURNING id",
            {"c": categoria, "n": nome},
        )
        for nome in (f"Equipamentos {n}", f"Consumo {n}")
    )
    setor = _inserir(
        con,
        "INSERT INTO core.setor (sigla, nome) VALUES (%(s)s, %(n)s) RETURNING id",
        {"s": "T" + _letras(n), "n": f"Setor Teste {n}"},
    )
    local = _inserir(
        con,
        "INSERT INTO core.local_armazenagem (nome) VALUES (%(n)s) RETURNING id",
        {"n": f"Depósito Teste {n}"},
    )
    entrada = date(2020, 1, 1)
    pessoas = [_pessoa(con, setor, entrada) for _ in range(6)]
    return Base(
        subcategoria_serial=sub_serial,
        subcategoria_consumo=sub_consumo,
        setor=setor,
        local=local,
        pessoa=pessoas[0],
        pessoa2=pessoas[1],
        pessoa_transferida=_pessoa(con, setor, entrada, date(2025, 12, 31)),
        pessoa_nova=_pessoa(con, setor, date(2026, 6, 1)),
        admin=_usuario(con, pessoas[2], "ADMINISTRADOR"),
        estoquista=_usuario(con, pessoas[3], "ESTOQUISTA"),
        equipamentista=_usuario(con, pessoas[4], "EQUIPAMENTISTA"),
        consulta=_usuario(con, pessoas[5], "CONSULTA"),
        usuario_inativo=_usuario(con, _pessoa(con, setor, entrada), "ADMINISTRADOR", ativo=False),
    )


def criar_material(
    con: Conexao,
    base: Base,
    controle: str,
    prazo_horas: int | None = None,
    unidade_medida: str | None = None,
) -> int:
    n = next(_sequencia)
    return _inserir(
        con,
        "INSERT INTO core.material_tipo (codigo, nome, subcategoria_id, unidade_medida, "
        "controle, prazo_devolucao_horas, custo_unitario) "
        "VALUES (%(c)s, %(n)s, %(s)s, %(u)s, %(ct)s, %(p)s, 10) RETURNING id",
        {
            "c": f"TST-{n % 10000:04d}",
            "n": f"Material Teste {n}",
            "s": base.subcategoria_serial if controle == "SERIAL" else base.subcategoria_consumo,
            "u": unidade_medida or ("UN" if controle == "SERIAL" else "CX"),
            "ct": controle,
            "p": prazo_horas,
        },
    )


def criar_unidades(
    con: Conexao,
    base: Base,
    material: int,
    quantidade: int = 1,
    quando: datetime = T0,
) -> list[int]:
    """Incorpora unidades com BMP à carga (status DISPONIVEL)."""
    unidades = []
    for _ in range(quantidade):
        n = next(_sequencia)
        unidades.append(
            chamar_funcao(
                con,
                "registrar_entrada_unidade",
                p_material_tipo_id=material,
                p_local_id=base.local,
                p_executado_por=base.estoquista,
                p_bmp=f"{8000000 + n}",
                p_ocorrida_em=quando,
            )
        )
    return unidades


def criar_consumo_com_saldo(
    con: Conexao, base: Base, saldo: int, minimo: int = 10, maximo: int = 500
) -> int:
    """Material de consumo com saldo cadastrado e uma ENTRADA inicial (se saldo > 0)."""
    material = criar_material(con, base, "CONSUMO")
    chamar_funcao(
        con,
        "cadastrar_saldo_consumo",
        p_material_tipo_id=material,
        p_local_id=base.local,
        p_estoque_minimo=minimo,
        p_estoque_maximo=maximo,
        p_executado_por=base.estoquista,
    )
    if saldo > 0:
        chamar_funcao(
            con,
            "registrar_entrada_consumo",
            p_material_tipo_id=material,
            p_quantidade=saldo,
            p_executado_por=base.estoquista,
            p_ocorrida_em=T0,
            p_documento_ref="SALDO-INICIAL",
        )
    return material
