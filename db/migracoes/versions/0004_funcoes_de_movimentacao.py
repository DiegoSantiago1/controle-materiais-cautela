"""funções de movimentação (regras de negócio no banco)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-23

Toda movimentação passa por uma destas funções. Cada uma, numa única transação:
1. confere o perfil de quem executa;
2. trava a linha do estado atual (SELECT ... FOR UPDATE), para que duas operações
   simultâneas sobre a mesma unidade ou o mesmo saldo aconteçam uma depois da outra;
3. valida a regra de negócio (situação da unidade, saldo, pessoa, ordem cronológica);
4. atualiza o estado atual e grava a movimentação no histórico.

Por que no banco e não na aplicação: o gerador de dados (Python) e a API (Node, fase
seguinte) chamam as mesmas funções. A regra existe num lugar só e vale para qualquer
cliente.

Erros de regra usam SQLSTATE próprios (ALMxx), para que a aplicação e os testes
identifiquem o motivo sem depender do texto da mensagem:
  ALM01 estoque insuficiente             ALM07 estorno inválido
  ALM02 operação incompatível            ALM08 data inválida ou fora de ordem
  ALM03 pessoa fora da unidade na data   ALM09 registro inexistente
  ALM04 devolução por quem não detém     ALM10 parâmetro inválido
  ALM05 usuário sem permissão            ALM12 tentativa de alterar o histórico
  ALM06 transição de status proibida     (definido na 0003)
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCOES_AUXILIARES = r"""
-- Data local (Recife) de um instante. Independe do fuso da sessão.
CREATE FUNCTION core.data_local(p_momento timestamptz) RETURNS date
LANGUAGE sql IMMUTABLE AS $$
    SELECT (p_momento AT TIME ZONE 'America/Recife')::date
$$;

-- Texto opcional: espaço em branco nas pontas removido (inclui TAB e quebra de
-- linha); vazio vira NULL.
CREATE FUNCTION core._texto(p_texto text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(regexp_replace(p_texto, '^\s+|\s+$', '', 'g'), '')
$$;

CREATE FUNCTION core._exigir_perfil(p_usuario integer, p_perfis text[]) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_usuario core.usuario%ROWTYPE;
BEGIN
    SELECT * INTO v_usuario FROM core.usuario WHERE id = p_usuario;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Usuário % não existe.', p_usuario USING ERRCODE = 'ALM05';
    END IF;
    IF NOT v_usuario.ativo THEN
        RAISE EXCEPTION 'Usuário % está inativo.', v_usuario.login USING ERRCODE = 'ALM05';
    END IF;
    IF NOT v_usuario.perfil = ANY (p_perfis) THEN
        RAISE EXCEPTION 'Perfil % não pode executar esta operação (permitido: %).',
            v_usuario.perfil, array_to_string(p_perfis, ', ')
            USING ERRCODE = 'ALM05';
    END IF;
END;
$$;

CREATE FUNCTION core._exigir_pessoa_na_unidade(p_pessoa integer, p_momento timestamptz)
RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_entrada date;
    v_saida   date;
    v_dia     date := core.data_local(p_momento);
BEGIN
    SELECT data_entrada, data_saida INTO v_entrada, v_saida
    FROM core.pessoa WHERE id = p_pessoa;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Pessoa % não existe.', p_pessoa USING ERRCODE = 'ALM09';
    END IF;
    IF v_dia < v_entrada OR (v_saida IS NOT NULL AND v_dia >= v_saida) THEN
        RAISE EXCEPTION 'Pessoa % não está na unidade em % (entrada %, saída %).',
            p_pessoa, v_dia, v_entrada, coalesce(v_saida::text, '-')
            USING ERRCODE = 'ALM03';
    END IF;
END;
$$;

-- Momento informado: obrigatório e não anterior à última movimentação do mesmo
-- item. A ordem cronológica é o que permite reconstruir o estado pelo histórico.
CREATE FUNCTION core._exigir_ordem(p_momento timestamptz, p_ultimo timestamptz) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF p_momento IS NULL THEN
        RAISE EXCEPTION 'Data e hora da movimentação são obrigatórias.' USING ERRCODE = 'ALM08';
    END IF;
    IF p_ultimo IS NOT NULL AND p_momento < p_ultimo THEN
        RAISE EXCEPTION 'Movimentação em % é anterior à última registrada (%).',
            p_momento, p_ultimo
            USING ERRCODE = 'ALM08';
    END IF;
END;
$$;

CREATE FUNCTION core._ultimo_momento_unidade(p_unidade integer) RETURNS timestamptz
LANGUAGE sql STABLE AS $$
    SELECT max(ocorrida_em) FROM core.movimentacao WHERE unidade_id = p_unidade
$$;

CREATE FUNCTION core._ultimo_momento_material(p_material integer) RETURNS timestamptz
LANGUAGE sql STABLE AS $$
    SELECT max(ocorrida_em) FROM core.movimentacao WHERE material_tipo_id = p_material
$$;

-- Material de consumo: trava e devolve o saldo (erro claro se não for consumo).
CREATE FUNCTION core._travar_saldo(p_material integer) RETURNS core.saldo_consumo
LANGUAGE plpgsql AS $$
DECLARE
    v_saldo core.saldo_consumo%ROWTYPE;
BEGIN
    SELECT * INTO v_saldo FROM core.saldo_consumo
    WHERE material_tipo_id = p_material
    FOR UPDATE;
    IF NOT FOUND THEN
        IF EXISTS (SELECT 1 FROM core.material_tipo WHERE id = p_material) THEN
            RAISE EXCEPTION 'Material % não é de consumo (ou não tem saldo cadastrado).',
                p_material USING ERRCODE = 'ALM02';
        END IF;
        RAISE EXCEPTION 'Material % não existe.', p_material USING ERRCODE = 'ALM09';
    END IF;
    RETURN v_saldo;
END;
$$;

CREATE FUNCTION core._exigir_quantidade_positiva(p_quantidade integer) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF p_quantidade IS NULL OR p_quantidade <= 0 THEN
        RAISE EXCEPTION 'Quantidade deve ser maior que zero (recebido: %).',
            coalesce(p_quantidade::text, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
END;
$$;
"""

FUNCOES_SERIAL = r"""
-- Incorpora uma unidade nova à carga (material permanente). Devolve o id da unidade.
-- Sem BMP, a unidade fica aguardando tombamento.
CREATE FUNCTION core.registrar_entrada_unidade(
    p_material_tipo_id integer,
    p_local_id         integer,
    p_executado_por    integer,
    p_bmp              text        DEFAULT NULL,
    p_numero_serie     text        DEFAULT NULL,
    p_ocorrida_em      timestamptz DEFAULT now(),
    p_documento_ref    text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_controle text;
    v_ativo    boolean;
    v_status   text;
    v_unidade  integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR', 'ESTOQUISTA']);
    PERFORM core._exigir_ordem(p_ocorrida_em, NULL);

    SELECT controle, ativo INTO v_controle, v_ativo
    FROM core.material_tipo WHERE id = p_material_tipo_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Material % não existe.', p_material_tipo_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_controle <> 'SERIAL' THEN
        RAISE EXCEPTION 'Material % é de consumo: use registrar_entrada_consumo.',
            p_material_tipo_id USING ERRCODE = 'ALM02';
    END IF;
    IF NOT v_ativo THEN
        RAISE EXCEPTION 'Material % está inativo.', p_material_tipo_id USING ERRCODE = 'ALM02';
    END IF;

    v_status := CASE WHEN core._texto(p_bmp) IS NULL
                     THEN 'AGUARDANDO_TOMBAMENTO' ELSE 'DISPONIVEL' END;

    INSERT INTO core.unidade_patrimonial (material_tipo_id, bmp, numero_serie, local_id, status)
    VALUES (p_material_tipo_id, core._texto(p_bmp), core._texto(p_numero_serie),
            p_local_id, v_status)
    RETURNING id INTO v_unidade;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle, unidade_id,
        status_anterior, status_novo, executado_por, documento_ref, observacao)
    VALUES (
        p_ocorrida_em, 'ENTRADA', p_material_tipo_id, 'SERIAL', v_unidade,
        NULL, v_status, p_executado_por, core._texto(p_documento_ref), core._texto(p_observacao));

    RETURN v_unidade;
END;
$$;

-- Cautela: a unidade sai com uma pessoa. Devolve o id da movimentação.
CREATE FUNCTION core.registrar_retirada_unidade(
    p_unidade_id       integer,
    p_pessoa_id        integer,
    p_executado_por    integer,
    p_ocorrida_em      timestamptz DEFAULT now(),
    p_prazo_devolucao  timestamptz DEFAULT NULL,
    p_setor_destino_id integer     DEFAULT NULL,
    p_finalidade       text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_status     text;
    v_material   integer;
    v_prazo_h    integer;
    v_prazo      timestamptz;
    v_mov        bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);

    -- Trava a unidade: uma segunda retirada simultânea espera aqui e, quando
    -- prosseguir, já encontra a unidade CAUTELADA.
    SELECT u.status, u.material_tipo_id, m.prazo_devolucao_horas
    INTO v_status, v_material, v_prazo_h
    FROM core.unidade_patrimonial u
    JOIN core.material_tipo m ON m.id = u.material_tipo_id
    WHERE u.id = p_unidade_id
    FOR UPDATE OF u;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unidade % não existe.', p_unidade_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_prazo_h IS NULL THEN
        RAISE EXCEPTION 'Unidade % é de um material que não é cautelável.', p_unidade_id
            USING ERRCODE = 'ALM02';
    END IF;
    IF v_status <> 'DISPONIVEL' THEN
        RAISE EXCEPTION 'Unidade % está % e não pode ser retirada.', p_unidade_id, v_status
            USING ERRCODE = 'ALM02';
    END IF;

    PERFORM core._exigir_ordem(p_ocorrida_em, core._ultimo_momento_unidade(p_unidade_id));
    PERFORM core._exigir_pessoa_na_unidade(p_pessoa_id, p_ocorrida_em);

    v_prazo := coalesce(p_prazo_devolucao, p_ocorrida_em + make_interval(hours => v_prazo_h));
    IF v_prazo <= p_ocorrida_em THEN
        RAISE EXCEPTION 'Prazo de devolução (%) precisa ser posterior à retirada (%).',
            v_prazo, p_ocorrida_em USING ERRCODE = 'ALM10';
    END IF;

    UPDATE core.unidade_patrimonial
    SET status = 'CAUTELADA', detentor_id = p_pessoa_id
    WHERE id = p_unidade_id;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle, unidade_id,
        status_anterior, status_novo, pessoa_id, executado_por,
        setor_destino_id, finalidade, prazo_devolucao, observacao)
    VALUES (
        p_ocorrida_em, 'RETIRADA', v_material, 'SERIAL', p_unidade_id,
        'DISPONIVEL', 'CAUTELADA', p_pessoa_id, p_executado_por,
        p_setor_destino_id, core._texto(p_finalidade), v_prazo, core._texto(p_observacao))
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;

-- Devolução de uma cautela. O estado informado define a nova situação:
-- BOM -> DISPONIVEL, AVARIADO -> EM_MANUTENCAO, INSERVIVEL -> BAIXA_PENDENTE.
CREATE FUNCTION core.registrar_devolucao_unidade(
    p_unidade_id    integer,
    p_pessoa_id     integer,
    p_executado_por integer,
    p_ocorrida_em   timestamptz DEFAULT now(),
    p_estado        text        DEFAULT 'BOM',
    p_observacao    text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_status    text;
    v_detentor  integer;
    v_material  integer;
    v_novo      text;
    v_mov       bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);

    v_novo := CASE p_estado
                  WHEN 'BOM'        THEN 'DISPONIVEL'
                  WHEN 'AVARIADO'   THEN 'EM_MANUTENCAO'
                  WHEN 'INSERVIVEL' THEN 'BAIXA_PENDENTE'
              END;
    IF v_novo IS NULL THEN
        RAISE EXCEPTION 'Estado de devolução inválido: % (use BOM, AVARIADO ou INSERVIVEL).',
            coalesce(p_estado, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
    IF p_estado <> 'BOM' AND core._texto(p_observacao) IS NULL THEN
        RAISE EXCEPTION 'Devolução com material % exige observação descrevendo o problema.',
            p_estado USING ERRCODE = 'ALM10';
    END IF;

    SELECT status, detentor_id, material_tipo_id INTO v_status, v_detentor, v_material
    FROM core.unidade_patrimonial
    WHERE id = p_unidade_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unidade % não existe.', p_unidade_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_status <> 'CAUTELADA' THEN
        RAISE EXCEPTION 'Unidade % está % e não pode ser devolvida.', p_unidade_id, v_status
            USING ERRCODE = 'ALM02';
    END IF;
    IF v_detentor IS DISTINCT FROM p_pessoa_id THEN
        RAISE EXCEPTION 'Unidade % está com a pessoa %, não com a pessoa %.',
            p_unidade_id, v_detentor, p_pessoa_id USING ERRCODE = 'ALM04';
    END IF;

    PERFORM core._exigir_ordem(p_ocorrida_em, core._ultimo_momento_unidade(p_unidade_id));

    UPDATE core.unidade_patrimonial
    SET status = v_novo, detentor_id = NULL
    WHERE id = p_unidade_id;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle, unidade_id,
        status_anterior, status_novo, pessoa_id, executado_por,
        estado_devolucao, observacao)
    VALUES (
        p_ocorrida_em, 'DEVOLUCAO', v_material, 'SERIAL', p_unidade_id,
        'CAUTELADA', v_novo, p_pessoa_id, p_executado_por,
        p_estado, core._texto(p_observacao))
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;

-- Mudança de situação fora do ciclo de cautela (manutenção, não localizada, baixa,
-- tombamento). Só as transições da lista são aceitas; a justificativa é obrigatória.
CREATE FUNCTION core.alterar_status_unidade(
    p_unidade_id    integer,
    p_novo_status   text,
    p_executado_por integer,
    p_justificativa text,
    p_ocorrida_em   timestamptz DEFAULT now(),
    p_bmp           text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_status    text;
    v_detentor  integer;
    v_material  integer;
    v_bmp       text := core._texto(p_bmp);
    v_mov       bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        CASE WHEN p_novo_status = 'BAIXADA'
             THEN ARRAY['ADMINISTRADOR']
             ELSE ARRAY['ADMINISTRADOR', 'ESTOQUISTA'] END);

    IF core._texto(p_justificativa) IS NULL THEN
        RAISE EXCEPTION 'Mudança de situação exige justificativa.' USING ERRCODE = 'ALM10';
    END IF;

    SELECT status, detentor_id, material_tipo_id INTO v_status, v_detentor, v_material
    FROM core.unidade_patrimonial
    WHERE id = p_unidade_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unidade % não existe.', p_unidade_id USING ERRCODE = 'ALM09';
    END IF;

    -- "IS NULL OR": com p_novo_status NULL, o NOT IN daria NULL (e não true), e o IF
    -- deixaria passar. Lógica de três valores do SQL.
    IF p_novo_status IS NULL OR (v_status, p_novo_status) NOT IN (
        ('DISPONIVEL',            'EM_MANUTENCAO'),
        ('DISPONIVEL',            'NAO_LOCALIZADA'),
        ('DISPONIVEL',            'BAIXA_PENDENTE'),
        ('CAUTELADA',             'NAO_LOCALIZADA'),
        ('EM_MANUTENCAO',         'DISPONIVEL'),
        ('EM_MANUTENCAO',         'BAIXA_PENDENTE'),
        ('NAO_LOCALIZADA',        'DISPONIVEL'),
        ('NAO_LOCALIZADA',        'BAIXA_PENDENTE'),
        ('BAIXA_PENDENTE',        'BAIXADA'),
        ('BAIXA_PENDENTE',        'DISPONIVEL'),
        ('AGUARDANDO_TOMBAMENTO', 'DISPONIVEL')
    ) THEN
        RAISE EXCEPTION 'Transição de % para % não é permitida.',
            v_status, coalesce(p_novo_status, 'NULL') USING ERRCODE = 'ALM06';
    END IF;

    -- O tombamento (receber o BMP) é a única forma de sair de AGUARDANDO_TOMBAMENTO.
    IF (v_status = 'AGUARDANDO_TOMBAMENTO') <> (v_bmp IS NOT NULL) THEN
        RAISE EXCEPTION 'BMP só é informado no tombamento (e é obrigatório nele).'
            USING ERRCODE = 'ALM10';
    END IF;

    PERFORM core._exigir_ordem(p_ocorrida_em, core._ultimo_momento_unidade(p_unidade_id));

    UPDATE core.unidade_patrimonial
    SET status = p_novo_status,
        detentor_id = NULL,
        bmp = coalesce(v_bmp, bmp)
    WHERE id = p_unidade_id;

    -- Se a unidade estava cautelada, o histórico guarda com quem ela estava.
    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle, unidade_id,
        status_anterior, status_novo, pessoa_id, executado_por, documento_ref, observacao)
    VALUES (
        p_ocorrida_em, 'MUDANCA_STATUS', v_material, 'SERIAL', p_unidade_id,
        v_status, p_novo_status, v_detentor, p_executado_por,
        CASE WHEN v_bmp IS NOT NULL THEN 'BMP ' || v_bmp END,
        core._texto(p_justificativa))
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;
"""

FUNCOES_CONSUMO = r"""
-- Cadastra o saldo de um material de consumo (começa em zero; o saldo inicial
-- entra como uma ENTRADA, para o histórico explicar cada unidade do saldo).
CREATE FUNCTION core.cadastrar_saldo_consumo(
    p_material_tipo_id integer,
    p_local_id         integer,
    p_estoque_minimo   integer,
    p_estoque_maximo   integer,
    p_executado_por    integer
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR', 'ESTOQUISTA']);
    INSERT INTO core.saldo_consumo (
        material_tipo_id, local_id, quantidade, estoque_minimo, estoque_maximo)
    VALUES (p_material_tipo_id, p_local_id, 0, p_estoque_minimo, p_estoque_maximo);
END;
$$;

CREATE FUNCTION core.registrar_entrada_consumo(
    p_material_tipo_id integer,
    p_quantidade       integer,
    p_executado_por    integer,
    p_ocorrida_em      timestamptz DEFAULT now(),
    p_documento_ref    text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_saldo core.saldo_consumo;
    v_mov   bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR', 'ESTOQUISTA']);
    PERFORM core._exigir_quantidade_positiva(p_quantidade);
    v_saldo := core._travar_saldo(p_material_tipo_id);
    PERFORM core._exigir_ordem(p_ocorrida_em, core._ultimo_momento_material(p_material_tipo_id));

    UPDATE core.saldo_consumo SET quantidade = quantidade + p_quantidade
    WHERE material_tipo_id = p_material_tipo_id;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle,
        variacao, saldo_antes, saldo_depois, executado_por, documento_ref, observacao)
    VALUES (
        p_ocorrida_em, 'ENTRADA', p_material_tipo_id, 'CONSUMO',
        p_quantidade, v_saldo.quantidade, v_saldo.quantidade + p_quantidade,
        p_executado_por, core._texto(p_documento_ref), core._texto(p_observacao))
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;

CREATE FUNCTION core.registrar_retirada_consumo(
    p_material_tipo_id integer,
    p_quantidade       integer,
    p_pessoa_id        integer,
    p_executado_por    integer,
    p_ocorrida_em      timestamptz DEFAULT now(),
    p_setor_destino_id integer     DEFAULT NULL,
    p_finalidade       text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_saldo core.saldo_consumo;
    v_mov   bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);
    PERFORM core._exigir_quantidade_positiva(p_quantidade);
    -- Trava o saldo: duas retiradas simultâneas não enxergam o mesmo saldo.
    v_saldo := core._travar_saldo(p_material_tipo_id);
    IF p_quantidade > v_saldo.quantidade THEN
        RAISE EXCEPTION 'Estoque insuficiente do material %: saldo %, pedido %.',
            p_material_tipo_id, v_saldo.quantidade, p_quantidade USING ERRCODE = 'ALM01';
    END IF;
    PERFORM core._exigir_ordem(p_ocorrida_em, core._ultimo_momento_material(p_material_tipo_id));
    PERFORM core._exigir_pessoa_na_unidade(p_pessoa_id, p_ocorrida_em);

    UPDATE core.saldo_consumo SET quantidade = quantidade - p_quantidade
    WHERE material_tipo_id = p_material_tipo_id;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle,
        variacao, saldo_antes, saldo_depois, pessoa_id, executado_por,
        setor_destino_id, finalidade, observacao)
    VALUES (
        p_ocorrida_em, 'RETIRADA', p_material_tipo_id, 'CONSUMO',
        -p_quantidade, v_saldo.quantidade, v_saldo.quantidade - p_quantidade,
        p_pessoa_id, p_executado_por,
        p_setor_destino_id, core._texto(p_finalidade), core._texto(p_observacao))
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;

-- Ajuste de inventário: informa a quantidade CONTADA; o banco calcula a diferença.
-- Se a contagem bate com o saldo, nada é lançado (devolve NULL).
CREATE FUNCTION core.registrar_ajuste_consumo(
    p_material_tipo_id  integer,
    p_quantidade_contada integer,
    p_executado_por     integer,
    p_justificativa     text,
    p_ocorrida_em       timestamptz DEFAULT now()
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_saldo    core.saldo_consumo;
    v_variacao integer;
    v_mov      bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR', 'ESTOQUISTA']);
    IF p_quantidade_contada IS NULL OR p_quantidade_contada < 0 THEN
        RAISE EXCEPTION 'Quantidade contada inválida: %.',
            coalesce(p_quantidade_contada::text, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
    IF core._texto(p_justificativa) IS NULL THEN
        RAISE EXCEPTION 'Ajuste de inventário exige justificativa.' USING ERRCODE = 'ALM10';
    END IF;
    v_saldo := core._travar_saldo(p_material_tipo_id);
    PERFORM core._exigir_ordem(p_ocorrida_em, core._ultimo_momento_material(p_material_tipo_id));

    v_variacao := p_quantidade_contada - v_saldo.quantidade;
    IF v_variacao = 0 THEN
        RETURN NULL;
    END IF;

    UPDATE core.saldo_consumo SET quantidade = p_quantidade_contada
    WHERE material_tipo_id = p_material_tipo_id;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle,
        variacao, saldo_antes, saldo_depois, executado_por, observacao)
    VALUES (
        p_ocorrida_em, 'AJUSTE', p_material_tipo_id, 'CONSUMO',
        v_variacao, v_saldo.quantidade, p_quantidade_contada,
        p_executado_por, core._texto(p_justificativa))
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;
"""

FUNCAO_ESTORNO = r"""
-- Estorno: desfaz o efeito de uma movimentação registrando outra, em sentido
-- contrário. A original continua no histórico. Só o administrador estorna.
-- Regras: não se estorna um estorno, nem a mesma movimentação duas vezes, nem a
-- entrada de uma unidade (para isso existe a baixa); numa unidade, só a última
-- movimentação pode ser estornada (senão o histórico deixaria de fazer sentido).
CREATE FUNCTION core.estornar_movimentacao(
    p_movimentacao_id bigint,
    p_executado_por   integer,
    p_justificativa   text,
    p_ocorrida_em     timestamptz DEFAULT now()
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_orig       core.movimentacao%ROWTYPE;
    v_saldo      core.saldo_consumo;
    v_status     text;
    v_ultima     bigint;
    v_detentor   integer;
    v_mov        bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    IF core._texto(p_justificativa) IS NULL THEN
        RAISE EXCEPTION 'Estorno exige justificativa.' USING ERRCODE = 'ALM10';
    END IF;

    SELECT * INTO v_orig FROM core.movimentacao WHERE id = p_movimentacao_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Movimentação % não existe.', p_movimentacao_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_orig.tipo = 'ESTORNO' THEN
        RAISE EXCEPTION 'Não se estorna um estorno: registre a operação correta de novo.'
            USING ERRCODE = 'ALM07';
    END IF;

    IF v_orig.controle = 'CONSUMO' THEN
        v_saldo := core._travar_saldo(v_orig.material_tipo_id);
    ELSE
        IF v_orig.tipo = 'ENTRADA' THEN
            RAISE EXCEPTION 'A entrada de uma unidade não se estorna: use a baixa.'
                USING ERRCODE = 'ALM07';
        END IF;
        SELECT status INTO v_status FROM core.unidade_patrimonial
        WHERE id = v_orig.unidade_id FOR UPDATE;
    END IF;

    -- Conferido depois da trava: dois estornos simultâneos da mesma movimentação
    -- ficam em fila, e o segundo encontra o primeiro já gravado.
    IF EXISTS (SELECT 1 FROM core.movimentacao WHERE estorno_de_id = p_movimentacao_id) THEN
        RAISE EXCEPTION 'Movimentação % já foi estornada.', p_movimentacao_id
            USING ERRCODE = 'ALM07';
    END IF;

    IF v_orig.controle = 'CONSUMO' THEN
        PERFORM core._exigir_ordem(p_ocorrida_em,
                                   core._ultimo_momento_material(v_orig.material_tipo_id));
        IF v_saldo.quantidade - v_orig.variacao < 0 THEN
            RAISE EXCEPTION 'Estorno deixaria o saldo negativo (saldo %, estorno %).',
                v_saldo.quantidade, -v_orig.variacao USING ERRCODE = 'ALM01';
        END IF;

        UPDATE core.saldo_consumo SET quantidade = quantidade - v_orig.variacao
        WHERE material_tipo_id = v_orig.material_tipo_id;

        INSERT INTO core.movimentacao (
            ocorrida_em, tipo, material_tipo_id, controle,
            variacao, saldo_antes, saldo_depois, pessoa_id, executado_por,
            observacao, estorno_de_id)
        VALUES (
            p_ocorrida_em, 'ESTORNO', v_orig.material_tipo_id, 'CONSUMO',
            -v_orig.variacao, v_saldo.quantidade, v_saldo.quantidade - v_orig.variacao,
            v_orig.pessoa_id, p_executado_por,
            core._texto(p_justificativa), p_movimentacao_id)
        RETURNING id INTO v_mov;
        RETURN v_mov;
    END IF;

    SELECT id INTO v_ultima FROM core.movimentacao
    WHERE unidade_id = v_orig.unidade_id
    ORDER BY ocorrida_em DESC, id DESC
    LIMIT 1;
    IF v_ultima <> p_movimentacao_id THEN
        RAISE EXCEPTION 'Só a última movimentação da unidade pode ser estornada (a última é %).',
            v_ultima USING ERRCODE = 'ALM07';
    END IF;
    IF v_status IS DISTINCT FROM v_orig.status_novo THEN
        RAISE EXCEPTION 'Estado da unidade (%) diverge do histórico (%).',
            v_status, v_orig.status_novo USING ERRCODE = 'ALM07';
    END IF;
    PERFORM core._exigir_ordem(p_ocorrida_em, v_orig.ocorrida_em);

    -- Voltando a CAUTELADA, o detentor é quem estava registrado na original.
    v_detentor := CASE WHEN v_orig.status_anterior = 'CAUTELADA' THEN v_orig.pessoa_id END;

    UPDATE core.unidade_patrimonial
    SET status = v_orig.status_anterior,
        detentor_id = v_detentor,
        bmp = CASE WHEN v_orig.status_anterior = 'AGUARDANDO_TOMBAMENTO' THEN NULL ELSE bmp END
    WHERE id = v_orig.unidade_id;

    INSERT INTO core.movimentacao (
        ocorrida_em, tipo, material_tipo_id, controle, unidade_id,
        status_anterior, status_novo, pessoa_id, executado_por, observacao, estorno_de_id)
    VALUES (
        p_ocorrida_em, 'ESTORNO', v_orig.material_tipo_id, 'SERIAL', v_orig.unidade_id,
        v_orig.status_novo, v_orig.status_anterior, v_orig.pessoa_id, p_executado_por,
        core._texto(p_justificativa), p_movimentacao_id)
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;
"""

VIEW_DIVERGENCIA = r"""
-- Auditoria do estado: compara o estado atual com o que o histórico reconstrói.
-- Deve estar sempre vazia. Qualquer linha aqui é um defeito (ex.: alguém alterou a
-- tabela de estado sem passar pelas funções).
CREATE VIEW core.vw_divergencia_estado AS
WITH ultima_mov_unidade AS (
    SELECT DISTINCT ON (unidade_id)
        unidade_id,
        status_novo,
        CASE WHEN status_novo = 'CAUTELADA' THEN pessoa_id END AS detentor_id
    FROM core.movimentacao
    WHERE unidade_id IS NOT NULL
    ORDER BY unidade_id, ocorrida_em DESC, id DESC
),
soma_consumo AS (
    SELECT material_tipo_id, sum(variacao)::integer AS quantidade
    FROM core.movimentacao
    WHERE controle = 'CONSUMO'
    GROUP BY material_tipo_id
)
SELECT
    'UNIDADE'::text AS item,
    u.id AS referencia_id,
    format('status=%s detentor=%s', u.status, u.detentor_id) AS estado_atual,
    format('status=%s detentor=%s', h.status_novo, h.detentor_id) AS estado_pelo_historico
FROM core.unidade_patrimonial u
LEFT JOIN ultima_mov_unidade h ON h.unidade_id = u.id
WHERE h.unidade_id IS NULL
   OR u.status IS DISTINCT FROM h.status_novo
   OR u.detentor_id IS DISTINCT FROM h.detentor_id
UNION ALL
SELECT
    'SALDO',
    s.material_tipo_id,
    format('quantidade=%s', s.quantidade),
    format('quantidade=%s', coalesce(h.quantidade, 0))
FROM core.saldo_consumo s
LEFT JOIN soma_consumo h ON h.material_tipo_id = s.material_tipo_id
WHERE s.quantidade <> coalesce(h.quantidade, 0);
"""


def upgrade() -> None:
    op.execute(FUNCOES_AUXILIARES)
    op.execute(FUNCOES_SERIAL)
    op.execute(FUNCOES_CONSUMO)
    op.execute(FUNCAO_ESTORNO)
    op.execute(VIEW_DIVERGENCIA)


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW core.vw_divergencia_estado;
        DROP FUNCTION core.estornar_movimentacao(bigint, integer, text, timestamptz);
        DROP FUNCTION core.registrar_ajuste_consumo(integer, integer, integer, text, timestamptz);
        DROP FUNCTION core.registrar_retirada_consumo(
            integer, integer, integer, integer, timestamptz, integer, text, text);
        DROP FUNCTION core.registrar_entrada_consumo(
            integer, integer, integer, timestamptz, text, text);
        DROP FUNCTION core.cadastrar_saldo_consumo(integer, integer, integer, integer, integer);
        DROP FUNCTION core.alterar_status_unidade(
            integer, text, integer, text, timestamptz, text);
        DROP FUNCTION core.registrar_devolucao_unidade(
            integer, integer, integer, timestamptz, text, text);
        DROP FUNCTION core.registrar_retirada_unidade(
            integer, integer, integer, timestamptz, timestamptz, integer, text, text);
        DROP FUNCTION core.registrar_entrada_unidade(
            integer, integer, integer, text, text, timestamptz, text, text);
        DROP FUNCTION core._exigir_quantidade_positiva(integer);
        DROP FUNCTION core._travar_saldo(integer);
        DROP FUNCTION core._ultimo_momento_material(integer);
        DROP FUNCTION core._ultimo_momento_unidade(integer);
        DROP FUNCTION core._exigir_ordem(timestamptz, timestamptz);
        DROP FUNCTION core._exigir_pessoa_na_unidade(integer, timestamptz);
        DROP FUNCTION core._exigir_perfil(integer, text[]);
        DROP FUNCTION core._texto(text);
        DROP FUNCTION core.data_local(timestamptz);
        """
    )
