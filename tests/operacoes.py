"""Operações de movimentação usadas pelos testes (retirar, devolver, alterar situação)."""

from almox.banco import Conexao, chamar_funcao

from .apoio import horas
from .cenario import Base


def estado(bd: Conexao, unidade: int) -> tuple[object, ...]:
    linha = bd.execute(
        "SELECT status, detentor_id FROM core.unidade_patrimonial WHERE id = %s", [unidade]
    ).fetchone()
    assert linha is not None
    return tuple(linha)


def retirar(
    bd: Conexao,
    base: Base,
    unidade: int,
    quando: float = 1,
    pessoa: int | None = None,
    **extra: object,
) -> object:
    return chamar_funcao(
        bd,
        "registrar_retirada_unidade",
        p_unidade_id=unidade,
        p_pessoa_id=pessoa or base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(quando),
        **extra,
    )


def devolver(
    bd: Conexao,
    base: Base,
    unidade: int,
    quando: float = 2,
    pessoa: int | None = None,
    estado_material: str = "BOM",
    observacao: str | None = None,
) -> object:
    return chamar_funcao(
        bd,
        "registrar_devolucao_unidade",
        p_unidade_id=unidade,
        p_pessoa_id=pessoa or base.pessoa,
        p_executado_por=base.equipamentista,
        p_ocorrida_em=horas(quando),
        p_estado=estado_material,
        p_observacao=observacao,
    )


def alterar(
    bd: Conexao,
    base: Base,
    unidade: int,
    novo: str | None,
    quando: float = 3,
    usuario: int | None = None,
    justificativa: str | None = "Conferência de carga",
    bmp: str | None = None,
) -> object:
    return chamar_funcao(
        bd,
        "alterar_status_unidade",
        p_unidade_id=unidade,
        p_novo_status=novo,
        p_executado_por=usuario or base.admin,
        p_justificativa=justificativa,
        p_ocorrida_em=horas(quando),
        p_bmp=bmp,
    )
