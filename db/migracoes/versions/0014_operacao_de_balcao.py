"""operação de balcão: retirada e devolução por quantidade, estoque e posse

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-02

1. Código de operação (uuid) no histórico: as N unidades de uma mesma retirada (ou
   devolução) ficam ligadas. É o que permite mostrar "3 escudos entregues às 08:35 pelo
   SGT Souza" e, depois, reconstruir o ciclo retirada -> posse -> devolução.
2. Estado do material na retirada (BOM ou REGULAR, este com observação obrigatória): se o
   material voltar avariado, dá para saber se ele já tinha saído com marcas de uso.
3. Retirada e devolução em lote. O material patrimonial continua rastreado por unidade
   (cada uma com seu BMP); pedir "3 escudos" escolhe 3 unidades disponíveis, travadas com
   FOR UPDATE SKIP LOCKED: dois equipamentistas atendendo ao mesmo tempo nunca recebem a
   mesma unidade, e um não espera o outro terminar. Cada unidade passa pela função de
   regra que já existia (registrar_retirada_unidade): nenhuma regra é reescrita.
4. Estoque mínimo também para material patrimonial (unidades disponíveis). O de consumo
   continua em core.saldo_consumo: uma fonte só para cada controle (CHECK).
5. Duas views para a aplicação: core.vw_estoque (total, disponível, em posse, manutenção,
   indisponível, mínimo e situação) e core.vw_posse (com quem está cada unidade, desde
   quando e quem entregou).

As três funções que ganham parâmetros novos (retirada e devolução de unidade, retirada de
consumo) são recriadas: em PL/pgSQL não se acrescenta parâmetro a uma função existente, e
uma segunda versão com outros parâmetros tornaria as chamadas ambíguas. Os parâmetros
novos vêm no fim, com valor padrão: quem já chamava (a carga, a API) continua igual.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

COLUNAS = r"""
ALTER TABLE core.movimentacao
    ADD COLUMN operacao uuid,
    ADD COLUMN estado_retirada text
        CONSTRAINT ck_mov_estado_retirada CHECK (estado_retirada IN ('BOM', 'REGULAR')),
    ADD CONSTRAINT ck_mov_estado_retirada_so_retirada
        CHECK (estado_retirada IS NULL OR tipo = 'RETIRADA');
COMMENT ON COLUMN core.movimentacao.operacao IS
    'Liga as movimentações de um mesmo atendimento no balcão (várias unidades de uma vez).';
CREATE INDEX ix_mov_operacao ON core.movimentacao (operacao) WHERE operacao IS NOT NULL;

ALTER TABLE core.material_tipo
    ADD COLUMN estoque_minimo integer CONSTRAINT ck_material_estoque_minimo
        CHECK (estoque_minimo >= 0),
    ADD CONSTRAINT ck_material_minimo_so_serial
        CHECK (controle = 'SERIAL' OR estoque_minimo IS NULL);
COMMENT ON COLUMN core.material_tipo.estoque_minimo IS
    'Material patrimonial: mínimo de unidades disponíveis. O de consumo fica em saldo_consumo.';
"""

FUNCOES_ANTIGAS = r"""
DROP FUNCTION core.registrar_retirada_unidade(
    integer, integer, integer, timestamptz, timestamptz, integer, text, text);
DROP FUNCTION core.registrar_devolucao_unidade(
    integer, integer, integer, timestamptz, text, text);
DROP FUNCTION core.registrar_retirada_consumo(
    integer, integer, integer, integer, timestamptz, integer, text, text);
"""

RETIRADA_UNIDADE = r"""
-- Cautela: a unidade sai com uma pessoa. Devolve o id da movimentação.
CREATE FUNCTION core.registrar_retirada_unidade(
    p_unidade_id       integer,
    p_pessoa_id        integer,
    p_executado_por    integer,
    p_ocorrida_em      timestamptz DEFAULT now(),
    p_prazo_devolucao  timestamptz DEFAULT NULL,
    p_setor_destino_id integer     DEFAULT NULL,
    p_finalidade       text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL,
    p_operacao         uuid        DEFAULT NULL,
    p_estado_retirada  text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_status     text;
    v_material   integer;
    v_prazo_h    integer;
    v_prazo      timestamptz;
    v_mov        bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);

    IF p_estado_retirada IS NOT NULL AND p_estado_retirada NOT IN ('BOM', 'REGULAR') THEN
        RAISE EXCEPTION 'Estado na retirada inválido: % (use BOM ou REGULAR).',
            p_estado_retirada USING ERRCODE = 'ALM10';
    END IF;
    IF p_estado_retirada = 'REGULAR' AND core._texto(p_observacao) IS NULL THEN
        RAISE EXCEPTION 'Material em estado regular exige observação descrevendo as marcas de uso.'
            USING ERRCODE = 'ALM10';
    END IF;

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
        setor_destino_id, finalidade, prazo_devolucao, observacao, operacao, estado_retirada)
    VALUES (
        p_ocorrida_em, 'RETIRADA', v_material, 'SERIAL', p_unidade_id,
        'DISPONIVEL', 'CAUTELADA', p_pessoa_id, p_executado_por,
        p_setor_destino_id, core._texto(p_finalidade), v_prazo, core._texto(p_observacao),
        p_operacao, p_estado_retirada)
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;
""".replace("{definer}", DEFINER)

DEVOLUCAO_UNIDADE = r"""
-- Devolução de uma cautela. O estado informado define a nova situação:
-- BOM -> DISPONIVEL, AVARIADO -> EM_MANUTENCAO, INSERVIVEL -> BAIXA_PENDENTE.
CREATE FUNCTION core.registrar_devolucao_unidade(
    p_unidade_id    integer,
    p_pessoa_id     integer,
    p_executado_por integer,
    p_ocorrida_em   timestamptz DEFAULT now(),
    p_estado        text        DEFAULT 'BOM',
    p_observacao    text        DEFAULT NULL,
    p_operacao      uuid        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql {definer} AS $$
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
        estado_devolucao, observacao, operacao)
    VALUES (
        p_ocorrida_em, 'DEVOLUCAO', v_material, 'SERIAL', p_unidade_id,
        'CAUTELADA', v_novo, p_pessoa_id, p_executado_por,
        p_estado, core._texto(p_observacao), p_operacao)
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;
""".replace("{definer}", DEFINER)

RETIRADA_CONSUMO = r"""
CREATE FUNCTION core.registrar_retirada_consumo(
    p_material_tipo_id integer,
    p_quantidade       integer,
    p_pessoa_id        integer,
    p_executado_por    integer,
    p_ocorrida_em      timestamptz DEFAULT now(),
    p_setor_destino_id integer     DEFAULT NULL,
    p_finalidade       text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL,
    p_operacao         uuid        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql {definer} AS $$
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
        setor_destino_id, finalidade, observacao, operacao)
    VALUES (
        p_ocorrida_em, 'RETIRADA', p_material_tipo_id, 'CONSUMO',
        -p_quantidade, v_saldo.quantidade, v_saldo.quantidade - p_quantidade,
        p_pessoa_id, p_executado_por,
        p_setor_destino_id, core._texto(p_finalidade), core._texto(p_observacao), p_operacao)
    RETURNING id INTO v_mov;

    RETURN v_mov;
END;
$$;
""".replace("{definer}", DEFINER)

LOTES = r"""
-- Lista de unidades informada pelo cliente: não vazia, sem nulos, sem repetição, até 500.
CREATE FUNCTION core._exigir_lista_de_unidades(p_unidades integer[]) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF p_unidades IS NULL OR cardinality(p_unidades) = 0 THEN
        RAISE EXCEPTION 'Informe ao menos uma unidade.' USING ERRCODE = 'ALM10';
    END IF;
    IF cardinality(p_unidades) > 500 THEN
        RAISE EXCEPTION 'No máximo 500 unidades por operação (recebido: %).',
            cardinality(p_unidades) USING ERRCODE = 'ALM10';
    END IF;
    IF array_position(p_unidades, NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'A lista de unidades tem valor vazio.' USING ERRCODE = 'ALM10';
    END IF;
    IF (SELECT count(DISTINCT x) FROM unnest(p_unidades) x) <> cardinality(p_unidades) THEN
        RAISE EXCEPTION 'A mesma unidade aparece mais de uma vez.' USING ERRCODE = 'ALM10';
    END IF;
END;
$$;

-- Retirada de N unidades de um material (ou N do saldo, se for de consumo) numa transação.
-- Sem p_unidades, o banco escolhe as disponíveis (menor id primeiro). Com p_unidades, são
-- aquelas (o equipamentista leu os BMPs). Devolve o código da operação.
CREATE FUNCTION core.registrar_retirada_lote(
    p_material_tipo_id integer,
    p_quantidade       integer,
    p_pessoa_id        integer,
    p_executado_por    integer,
    p_operacao         uuid        DEFAULT NULL,
    p_estado_retirada  text        DEFAULT 'BOM',
    p_finalidade       text        DEFAULT NULL,
    p_observacao       text        DEFAULT NULL,
    p_unidades         integer[]   DEFAULT NULL,
    p_ocorrida_em      timestamptz DEFAULT now()
) RETURNS uuid
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_operacao    uuid := coalesce(p_operacao, gen_random_uuid());
    v_controle    text;
    v_nome        text;
    v_cautelavel  boolean;
    v_ids         integer[];
    v_disponiveis integer;
    v_unidade     integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);

    SELECT controle, nome, prazo_devolucao_horas IS NOT NULL
    INTO v_controle, v_nome, v_cautelavel
    FROM core.material_tipo WHERE id = p_material_tipo_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Material % não existe.', p_material_tipo_id USING ERRCODE = 'ALM09';
    END IF;

    IF p_unidades IS NOT NULL THEN
        PERFORM core._exigir_lista_de_unidades(p_unidades);
        IF v_controle <> 'SERIAL' THEN
            RAISE EXCEPTION 'Material de consumo não tem unidades com BMP.' USING ERRCODE = 'ALM02';
        END IF;
        IF p_quantidade IS NOT NULL AND p_quantidade <> cardinality(p_unidades) THEN
            RAISE EXCEPTION 'Quantidade (%) diferente do número de unidades informadas (%).',
                p_quantidade, cardinality(p_unidades) USING ERRCODE = 'ALM10';
        END IF;
        IF EXISTS (SELECT 1 FROM unnest(p_unidades) x
                   LEFT JOIN core.unidade_patrimonial u ON u.id = x
                   WHERE u.id IS NULL OR u.material_tipo_id <> p_material_tipo_id) THEN
            RAISE EXCEPTION 'Alguma unidade informada não existe ou não é de %.', v_nome
                USING ERRCODE = 'ALM10';
        END IF;
        -- Ordem fixa (id crescente) ao travar: duas operações sobre as mesmas unidades
        -- travam na mesma ordem e não entram em deadlock.
        SELECT array_agg(x ORDER BY x) INTO v_ids FROM unnest(p_unidades) x;
    ELSE
        IF p_quantidade IS NULL OR p_quantidade NOT BETWEEN 1 AND 500 THEN
            RAISE EXCEPTION 'Quantidade deve ficar entre 1 e 500 (recebido: %).',
                coalesce(p_quantidade::text, 'NULL') USING ERRCODE = 'ALM10';
        END IF;

        IF v_controle = 'CONSUMO' THEN
            PERFORM core.registrar_retirada_consumo(
                p_material_tipo_id => p_material_tipo_id,
                p_quantidade       => p_quantidade,
                p_pessoa_id        => p_pessoa_id,
                p_executado_por    => p_executado_por,
                p_ocorrida_em      => p_ocorrida_em,
                p_finalidade       => p_finalidade,
                p_observacao       => p_observacao,
                p_operacao         => v_operacao);
            RETURN v_operacao;
        END IF;

        IF NOT v_cautelavel THEN
            RAISE EXCEPTION '% não é cautelável.', v_nome USING ERRCODE = 'ALM02';
        END IF;
        -- SKIP LOCKED: unidades que outro equipamentista está retirando agora ficam de
        -- fora (em vez de esperar por elas); se faltar, a mensagem diz quantas há.
        SELECT array_agg(id ORDER BY id) INTO v_ids
        FROM (SELECT id FROM core.unidade_patrimonial
              WHERE material_tipo_id = p_material_tipo_id AND status = 'DISPONIVEL'
              ORDER BY id
              LIMIT p_quantidade
              FOR UPDATE SKIP LOCKED) livres;
        IF coalesce(cardinality(v_ids), 0) < p_quantidade THEN
            -- Contagem sem trava: inclui as que outro atendimento está retirando agora.
            SELECT count(*) INTO v_disponiveis FROM core.unidade_patrimonial
            WHERE material_tipo_id = p_material_tipo_id AND status = 'DISPONIVEL';
            IF v_disponiveis >= p_quantidade THEN
                RAISE EXCEPTION 'Parte das unidades de % está sendo retirada em outro '
                                'atendimento agora. Tente de novo em instantes.', v_nome
                    USING ERRCODE = 'ALM01';
            END IF;
            RAISE EXCEPTION 'Estoque insuficiente de %: % disponível(is), pedido %.',
                v_nome, v_disponiveis, p_quantidade USING ERRCODE = 'ALM01';
        END IF;
    END IF;

    FOREACH v_unidade IN ARRAY v_ids LOOP
        PERFORM core.registrar_retirada_unidade(
            p_unidade_id      => v_unidade,
            p_pessoa_id       => p_pessoa_id,
            p_executado_por   => p_executado_por,
            p_ocorrida_em     => p_ocorrida_em,
            p_finalidade      => p_finalidade,
            p_observacao      => p_observacao,
            p_operacao        => v_operacao,
            p_estado_retirada => coalesce(p_estado_retirada, 'BOM'));
    END LOOP;
    RETURN v_operacao;
END;
$$;

-- Devolução de várias unidades que estão com a mesma pessoa, no mesmo estado. Para
-- estados diferentes (2 bons e 1 avariado), são duas operações.
CREATE FUNCTION core.registrar_devolucao_lote(
    p_unidades      integer[],
    p_pessoa_id     integer,
    p_executado_por integer,
    p_estado        text        DEFAULT 'BOM',
    p_observacao    text        DEFAULT NULL,
    p_operacao      uuid        DEFAULT NULL,
    p_ocorrida_em   timestamptz DEFAULT now()
) RETURNS uuid
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_operacao uuid := coalesce(p_operacao, gen_random_uuid());
    v_unidade  integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);
    PERFORM core._exigir_lista_de_unidades(p_unidades);
    FOR v_unidade IN SELECT x FROM unnest(p_unidades) x ORDER BY x LOOP
        PERFORM core.registrar_devolucao_unidade(
            p_unidade_id    => v_unidade,
            p_pessoa_id     => p_pessoa_id,
            p_executado_por => p_executado_por,
            p_ocorrida_em   => p_ocorrida_em,
            p_estado        => p_estado,
            p_observacao    => p_observacao,
            p_operacao      => v_operacao);
    END LOOP;
    RETURN v_operacao;
END;
$$;
""".replace("{definer}", DEFINER)

VIEWS = r"""
-- Estoque por material. Patrimonial: contagem das unidades por situação (BAIXADA não
-- conta no total: saiu da carga). Consumo: o saldo, todo disponível.
-- Situação (a mesma régua da análise A4): crítico = disponível <= 50% do mínimo.
CREATE VIEW core.vw_estoque AS
WITH unidades AS (
    SELECT material_tipo_id,
           count(*) FILTER (WHERE status <> 'BAIXADA')        AS total,
           count(*) FILTER (WHERE status = 'DISPONIVEL')      AS disponivel,
           count(*) FILTER (WHERE status = 'CAUTELADA')       AS em_posse,
           count(*) FILTER (WHERE status = 'EM_MANUTENCAO')   AS em_manutencao,
           count(*) FILTER (WHERE status IN ('NAO_LOCALIZADA', 'BAIXA_PENDENTE',
                                             'AGUARDANDO_TOMBAMENTO')) AS indisponivel
    FROM core.unidade_patrimonial
    GROUP BY material_tipo_id
),
base AS (
    SELECT m.id AS material_tipo_id, m.codigo, m.nome, m.descricao, m.controle,
           m.unidade_medida, m.prazo_devolucao_horas, m.custo_unitario, m.ativo,
           c.id AS categoria_id, c.nome AS categoria, s.id AS subcategoria_id,
           s.nome AS subcategoria,
           CASE WHEN m.controle = 'SERIAL' THEN coalesce(u.total, 0)
                ELSE coalesce(sc.quantidade, 0) END::integer AS total,
           CASE WHEN m.controle = 'SERIAL' THEN coalesce(u.disponivel, 0)
                ELSE coalesce(sc.quantidade, 0) END::integer AS disponivel,
           coalesce(u.em_posse, 0)::integer      AS em_posse,
           coalesce(u.em_manutencao, 0)::integer AS em_manutencao,
           coalesce(u.indisponivel, 0)::integer  AS indisponivel,
           CASE WHEN m.controle = 'SERIAL' THEN m.estoque_minimo
                ELSE sc.estoque_minimo END AS estoque_minimo
    FROM core.material_tipo m
    JOIN core.subcategoria s ON s.id = m.subcategoria_id
    JOIN core.categoria c ON c.id = s.categoria_id
    LEFT JOIN unidades u ON u.material_tipo_id = m.id
    LEFT JOIN core.saldo_consumo sc ON sc.material_tipo_id = m.id
)
SELECT base.*,
       CASE WHEN disponivel = 0 THEN 'SEM_ESTOQUE'
            WHEN estoque_minimo > 0 AND disponivel <= estoque_minimo / 2.0 THEN 'CRITICO'
            WHEN disponivel < estoque_minimo THEN 'ABAIXO_DO_MINIMO'
            ELSE 'NORMAL' END AS situacao
FROM base;

-- Com quem está cada unidade cautelada, desde quando e quem entregou. A retirada que
-- abriu a posse é a última RETIRADA da unidade.
CREATE VIEW core.vw_posse AS
SELECT u.id AS unidade_id, u.bmp, u.numero_serie,
       m.id AS material_tipo_id, m.codigo, m.nome AS material,
       c.nome AS categoria,
       p.id AS pessoa_id, p.posto_graduacao, p.nome_guerra, p.nome, p.matricula,
       se.sigla AS setor,
       r.id AS retirada_id, r.ocorrida_em AS retirada_em, r.prazo_devolucao AS prazo,
       r.operacao, r.estado_retirada, r.finalidade, r.observacao,
       r.executado_por AS entregue_por_usuario_id,
       pe.posto_graduacao AS entregue_por_posto, pe.nome_guerra AS entregue_por_guerra
FROM core.unidade_patrimonial u
JOIN core.material_tipo m ON m.id = u.material_tipo_id
JOIN core.subcategoria s ON s.id = m.subcategoria_id
JOIN core.categoria c ON c.id = s.categoria_id
JOIN core.pessoa p ON p.id = u.detentor_id
JOIN core.setor se ON se.id = p.setor_id
JOIN LATERAL (
    SELECT mv.id, mv.ocorrida_em, mv.prazo_devolucao, mv.operacao, mv.estado_retirada,
           mv.finalidade, mv.observacao, mv.executado_por
    FROM core.movimentacao mv
    WHERE mv.unidade_id = u.id AND mv.tipo = 'RETIRADA'
    ORDER BY mv.ocorrida_em DESC, mv.id DESC
    LIMIT 1
) r ON true
JOIN core.usuario ue ON ue.id = r.executado_por
JOIN core.pessoa pe ON pe.id = ue.pessoa_id
WHERE u.status = 'CAUTELADA';
"""

PERMISSOES = r"""
REVOKE EXECUTE ON FUNCTION core.registrar_retirada_unidade, core.registrar_devolucao_unidade,
    core.registrar_retirada_consumo, core.registrar_retirada_lote,
    core.registrar_devolucao_lote, core._exigir_lista_de_unidades FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        GRANT EXECUTE ON FUNCTION core.registrar_retirada_unidade,
                                  core.registrar_devolucao_unidade,
                                  core.registrar_retirada_lote,
                                  core.registrar_devolucao_lote
            TO almox_aplicacao;
        GRANT SELECT ON core.vw_estoque, core.vw_posse, core.saldo_consumo
            TO almox_aplicacao;
    END IF;
END;
$$;
"""

# --- downgrade: as três funções exatamente como eram (0004 + SECURITY DEFINER da 0012)
RETIRADA_UNIDADE_ANTIGA = r"""
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
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_status     text;
    v_material   integer;
    v_prazo_h    integer;
    v_prazo      timestamptz;
    v_mov        bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);
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
""".replace("{definer}", DEFINER)

DEVOLUCAO_UNIDADE_ANTIGA = r"""
CREATE FUNCTION core.registrar_devolucao_unidade(
    p_unidade_id    integer,
    p_pessoa_id     integer,
    p_executado_por integer,
    p_ocorrida_em   timestamptz DEFAULT now(),
    p_estado        text        DEFAULT 'BOM',
    p_observacao    text        DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql {definer} AS $$
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
""".replace("{definer}", DEFINER)

RETIRADA_CONSUMO_ANTIGA = r"""
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
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_saldo core.saldo_consumo;
    v_mov   bigint;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por,
        ARRAY['ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA']);
    PERFORM core._exigir_quantidade_positiva(p_quantidade);
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
""".replace("{definer}", DEFINER)

PERMISSOES_ANTIGAS = r"""
REVOKE EXECUTE ON FUNCTION core.registrar_retirada_unidade, core.registrar_devolucao_unidade,
    core.registrar_retirada_consumo FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        GRANT EXECUTE ON FUNCTION core.registrar_retirada_unidade,
                                  core.registrar_devolucao_unidade
            TO almox_aplicacao;
        REVOKE SELECT ON core.saldo_consumo FROM almox_aplicacao;
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute(COLUNAS)
    op.execute(FUNCOES_ANTIGAS)
    op.execute(RETIRADA_UNIDADE)
    op.execute(DEVOLUCAO_UNIDADE)
    op.execute(RETIRADA_CONSUMO)
    op.execute(LOTES)
    op.execute(VIEWS)
    op.execute(PERMISSOES)


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW core.vw_posse;
        DROP VIEW core.vw_estoque;
        DROP FUNCTION core.registrar_devolucao_lote(
            integer[], integer, integer, text, text, uuid, timestamptz);
        DROP FUNCTION core.registrar_retirada_lote(
            integer, integer, integer, integer, uuid, text, text, text, integer[], timestamptz);
        DROP FUNCTION core._exigir_lista_de_unidades(integer[]);
        DROP FUNCTION core.registrar_retirada_unidade(
            integer, integer, integer, timestamptz, timestamptz, integer, text, text, uuid, text);
        DROP FUNCTION core.registrar_devolucao_unidade(
            integer, integer, integer, timestamptz, text, text, uuid);
        DROP FUNCTION core.registrar_retirada_consumo(
            integer, integer, integer, integer, timestamptz, integer, text, text, uuid);
        """
    )
    op.execute(RETIRADA_UNIDADE_ANTIGA)
    op.execute(DEVOLUCAO_UNIDADE_ANTIGA)
    op.execute(RETIRADA_CONSUMO_ANTIGA)
    op.execute(PERMISSOES_ANTIGAS)
    op.execute(
        """
        ALTER TABLE core.material_tipo
            DROP CONSTRAINT ck_material_minimo_so_serial,
            DROP COLUMN estoque_minimo;
        DROP INDEX core.ix_mov_operacao;
        ALTER TABLE core.movimentacao
            DROP CONSTRAINT ck_mov_estado_retirada_so_retirada,
            DROP COLUMN estado_retirada,
            DROP COLUMN operacao;
        """
    )
