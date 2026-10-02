"""administração pela aplicação, auditoria e escrita só com sessão válida

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-02

1. Funções do administrador: categorias e subcategorias, materiais (cadastro e edição),
   entrada de unidades em lote, militares (cadastro, edição e saída da unidade) e
   usuários (cadastro, perfil, ativação). Cada uma valida e devolve uma mensagem clara
   (ALM10 parâmetro, ALM11 duplicado), em vez de deixar estourar a constraint.
2. core.auditoria: quem fez o quê nos cadastros, quando, com o antes e o depois. Só
   INSERT, como o histórico de movimentações (as movimentações já são a auditoria do
   estoque).
3. Escrita só com sessão válida (schema app). Antes (D20), o banco confiava no
   p_executado_por que a API mandava. Com funções que trocam senha e perfil, isso deixa
   de bastar: com uma injeção de SQL na API, qualquer um chamaria a função passando o id
   de um administrador. Agora o usuário do banco da API executa SÓ as funções app.*, que
   recebem o hash do token da sessão e descobrem no banco quem está logado. Sem o token
   de um administrador logado, nenhuma função de administrador roda.

Proteções contra se trancar para fora: ninguém tira o próprio acesso de administrador,
sempre sobra pelo menos um administrador ativo, e quem sai da unidade com material em
posse é recusado (primeiro se recebe a devolução).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

AUDITORIA = r"""
CREATE TABLE core.auditoria (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocorrida_em   timestamptz NOT NULL DEFAULT clock_timestamp(),
    executado_por integer NOT NULL REFERENCES core.usuario (id),
    acao          text NOT NULL CONSTRAINT ck_auditoria_acao CHECK (acao ~ '^[A-Z_]{3,40}$'),
    entidade      text NOT NULL CONSTRAINT ck_auditoria_entidade CHECK (entidade IN (
                      'CATEGORIA', 'SUBCATEGORIA', 'MATERIAL', 'PESSOA', 'USUARIO'
                  )),
    entidade_id   integer NOT NULL,
    detalhe       jsonb NOT NULL DEFAULT '{}'::jsonb
);
COMMENT ON TABLE core.auditoria IS
    'Alterações de cadastro feitas pela aplicação. Só INSERT (triggers bloqueiam o resto).';
CREATE INDEX ix_auditoria_tempo ON core.auditoria (ocorrida_em);
CREATE INDEX ix_auditoria_entidade ON core.auditoria (entidade, entidade_id);

CREATE FUNCTION core.tg_auditoria_imutavel() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'A auditoria é imutável (% bloqueado).', TG_OP USING ERRCODE = 'ALM12';
END;
$$;
CREATE TRIGGER tg_auditoria_sem_update_delete
    BEFORE UPDATE OR DELETE ON core.auditoria
    FOR EACH ROW EXECUTE FUNCTION core.tg_auditoria_imutavel();
CREATE TRIGGER tg_auditoria_sem_truncate
    BEFORE TRUNCATE ON core.auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION core.tg_auditoria_imutavel();

CREATE FUNCTION core._auditar(
    p_executado_por integer, p_acao text, p_entidade text, p_entidade_id integer,
    p_detalhe jsonb DEFAULT '{}'::jsonb
) RETURNS void
LANGUAGE sql AS $$
    INSERT INTO core.auditoria (executado_por, acao, entidade, entidade_id, detalhe)
    VALUES (p_executado_por, p_acao, p_entidade, p_entidade_id, coalesce(p_detalhe, '{}'));
$$;
"""

CATEGORIAS = r"""
CREATE FUNCTION core.cadastrar_categoria(p_nome text, p_executado_por integer)
RETURNS integer
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_nome text := core._texto(p_nome);
    v_id   integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    IF v_nome IS NULL THEN
        RAISE EXCEPTION 'Informe o nome da categoria.' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.categoria WHERE lower(nome) = lower(v_nome)) THEN
        RAISE EXCEPTION 'Já existe a categoria "%".', v_nome USING ERRCODE = 'ALM11';
    END IF;
    INSERT INTO core.categoria (nome) VALUES (v_nome) RETURNING id INTO v_id;
    PERFORM core._auditar(p_executado_por, 'CADASTRAR', 'CATEGORIA', v_id,
                          jsonb_build_object('nome', v_nome));
    RETURN v_id;
END;
$$;

CREATE FUNCTION core.renomear_categoria(p_categoria_id integer, p_nome text,
                                        p_executado_por integer)
RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_nome  text := core._texto(p_nome);
    v_antes text;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    SELECT nome INTO v_antes FROM core.categoria WHERE id = p_categoria_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Categoria % não existe.', p_categoria_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_nome IS NULL THEN
        RAISE EXCEPTION 'Informe o nome da categoria.' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.categoria
               WHERE lower(nome) = lower(v_nome) AND id <> p_categoria_id) THEN
        RAISE EXCEPTION 'Já existe a categoria "%".', v_nome USING ERRCODE = 'ALM11';
    END IF;
    UPDATE core.categoria SET nome = v_nome WHERE id = p_categoria_id;
    PERFORM core._auditar(p_executado_por, 'RENOMEAR', 'CATEGORIA', p_categoria_id,
                          jsonb_build_object('antes', v_antes, 'depois', v_nome));
END;
$$;

CREATE FUNCTION core.cadastrar_subcategoria(p_categoria_id integer, p_nome text,
                                            p_executado_por integer)
RETURNS integer
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_nome text := core._texto(p_nome);
    v_id   integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    IF NOT EXISTS (SELECT 1 FROM core.categoria WHERE id = p_categoria_id) THEN
        RAISE EXCEPTION 'Categoria % não existe.', p_categoria_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_nome IS NULL THEN
        RAISE EXCEPTION 'Informe o nome da subcategoria.' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.subcategoria
               WHERE categoria_id = p_categoria_id AND lower(nome) = lower(v_nome)) THEN
        RAISE EXCEPTION 'Já existe a subcategoria "%" nesta categoria.', v_nome
            USING ERRCODE = 'ALM11';
    END IF;
    INSERT INTO core.subcategoria (categoria_id, nome) VALUES (p_categoria_id, v_nome)
    RETURNING id INTO v_id;
    PERFORM core._auditar(p_executado_por, 'CADASTRAR', 'SUBCATEGORIA', v_id,
                          jsonb_build_object('nome', v_nome, 'categoria_id', p_categoria_id));
    RETURN v_id;
END;
$$;

CREATE FUNCTION core.renomear_subcategoria(p_subcategoria_id integer, p_nome text,
                                           p_executado_por integer)
RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_nome      text := core._texto(p_nome);
    v_antes     text;
    v_categoria integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    SELECT nome, categoria_id INTO v_antes, v_categoria
    FROM core.subcategoria WHERE id = p_subcategoria_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Subcategoria % não existe.', p_subcategoria_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_nome IS NULL THEN
        RAISE EXCEPTION 'Informe o nome da subcategoria.' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.subcategoria
               WHERE categoria_id = v_categoria AND lower(nome) = lower(v_nome)
                 AND id <> p_subcategoria_id) THEN
        RAISE EXCEPTION 'Já existe a subcategoria "%" nesta categoria.', v_nome
            USING ERRCODE = 'ALM11';
    END IF;
    UPDATE core.subcategoria SET nome = v_nome WHERE id = p_subcategoria_id;
    PERFORM core._auditar(p_executado_por, 'RENOMEAR', 'SUBCATEGORIA', p_subcategoria_id,
                          jsonb_build_object('antes', v_antes, 'depois', v_nome));
END;
$$;
""".replace("{definer}", DEFINER)

MATERIAIS = r"""
-- Cria um tipo de material. O código segue o padrão AAA-9999: três letras do nome (sem
-- acento) e o próximo número livre. Patrimonial (SERIAL) é contado em unidades com BMP;
-- consumo (CONSUMO) ganha o saldo, com local, mínimo e máximo, já na criação.
CREATE FUNCTION core.cadastrar_material(
    p_nome                  text,
    p_subcategoria_id       integer,
    p_controle              text,
    p_executado_por         integer,
    p_unidade_medida        text    DEFAULT 'UN',
    p_prazo_devolucao_horas integer DEFAULT NULL,
    p_estoque_minimo        integer DEFAULT NULL,
    p_estoque_maximo        integer DEFAULT NULL,
    p_local_id              integer DEFAULT NULL,
    p_custo_unitario        numeric DEFAULT 0,
    p_descricao             text    DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_nome     text := core._texto(p_nome);
    v_prefixo  text;
    v_numero   integer;
    v_codigo   text;
    v_id       integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);

    IF v_nome IS NULL THEN
        RAISE EXCEPTION 'Informe o nome do material.' USING ERRCODE = 'ALM10';
    END IF;
    IF p_controle IS NULL OR p_controle NOT IN ('SERIAL', 'CONSUMO') THEN
        RAISE EXCEPTION 'Tipo de controle inválido: % (use SERIAL ou CONSUMO).',
            coalesce(p_controle, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.subcategoria WHERE id = p_subcategoria_id) THEN
        RAISE EXCEPTION 'Subcategoria % não existe.', p_subcategoria_id USING ERRCODE = 'ALM09';
    END IF;
    IF EXISTS (SELECT 1 FROM core.material_tipo WHERE lower(nome) = lower(v_nome)) THEN
        RAISE EXCEPTION 'Já existe um material chamado "%".', v_nome USING ERRCODE = 'ALM11';
    END IF;
    IF p_custo_unitario IS NULL OR p_custo_unitario < 0 THEN
        RAISE EXCEPTION 'Valor unitário não pode ser negativo.' USING ERRCODE = 'ALM10';
    END IF;
    IF p_estoque_minimo IS NOT NULL AND p_estoque_minimo < 0 THEN
        RAISE EXCEPTION 'Estoque mínimo não pode ser negativo.' USING ERRCODE = 'ALM10';
    END IF;

    IF p_controle = 'SERIAL' THEN
        IF p_unidade_medida IS DISTINCT FROM 'UN' THEN
            RAISE EXCEPTION 'Material patrimonial é contado em unidades (UN).'
                USING ERRCODE = 'ALM10';
        END IF;
        IF p_prazo_devolucao_horas IS NOT NULL
           AND p_prazo_devolucao_horas NOT BETWEEN 1 AND 8760 THEN
            RAISE EXCEPTION 'Prazo de devolução deve ficar entre 1 e 8760 horas.'
                USING ERRCODE = 'ALM10';
        END IF;
    ELSE
        IF p_prazo_devolucao_horas IS NOT NULL THEN
            RAISE EXCEPTION 'Material de consumo não é cautelado (não tem prazo de devolução).'
                USING ERRCODE = 'ALM10';
        END IF;
        IF p_unidade_medida IS NULL OR p_unidade_medida NOT IN (
               'UN', 'CX', 'PCT', 'RESMA', 'L', 'GL', 'KG', 'M', 'ROLO', 'PAR', 'FRASCO') THEN
            RAISE EXCEPTION 'Unidade de medida inválida: %.', coalesce(p_unidade_medida, 'NULL')
                USING ERRCODE = 'ALM10';
        END IF;
        IF p_estoque_minimo IS NULL OR p_estoque_maximo IS NULL
           OR p_estoque_maximo <= 0 OR p_estoque_maximo < p_estoque_minimo THEN
            RAISE EXCEPTION 'Consumo exige estoque mínimo e máximo (máximo > 0 e >= mínimo).'
                USING ERRCODE = 'ALM10';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM core.local_armazenagem WHERE id = p_local_id) THEN
            RAISE EXCEPTION 'Informe um local de armazenagem existente.' USING ERRCODE = 'ALM09';
        END IF;
    END IF;

    v_prefixo := rpad(left(regexp_replace(
                     upper(translate(v_nome, 'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                                             'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC')),
                     '[^A-Z]', '', 'g'), 3), 3, 'X');
    -- Dois cadastros simultâneos com o mesmo prefixo não podem pegar o mesmo número.
    PERFORM pg_advisory_xact_lock(hashtext('core.material_tipo.codigo'));
    SELECT coalesce(max(substr(codigo, 5)::integer), 0) + 1 INTO v_numero
    FROM core.material_tipo WHERE codigo LIKE v_prefixo || '-%';
    IF v_numero > 9999 THEN
        RAISE EXCEPTION 'Códigos do prefixo % esgotados.', v_prefixo USING ERRCODE = 'ALM10';
    END IF;
    v_codigo := v_prefixo || '-' || lpad(v_numero::text, 4, '0');

    INSERT INTO core.material_tipo (codigo, nome, descricao, subcategoria_id, unidade_medida,
                                    controle, prazo_devolucao_horas, custo_unitario,
                                    estoque_minimo)
    VALUES (v_codigo, v_nome, core._texto(p_descricao), p_subcategoria_id, p_unidade_medida,
            p_controle, p_prazo_devolucao_horas, p_custo_unitario,
            CASE WHEN p_controle = 'SERIAL' THEN p_estoque_minimo END)
    RETURNING id INTO v_id;

    IF p_controle = 'CONSUMO' THEN
        PERFORM core.cadastrar_saldo_consumo(v_id, p_local_id, p_estoque_minimo,
                                             p_estoque_maximo, p_executado_por);
    END IF;

    PERFORM core._auditar(p_executado_por, 'CADASTRAR', 'MATERIAL', v_id,
        jsonb_build_object('codigo', v_codigo, 'nome', v_nome, 'controle', p_controle,
                           'prazo_devolucao_horas', p_prazo_devolucao_horas,
                           'estoque_minimo', p_estoque_minimo));
    RETURN v_id;
END;
$$;

-- Edição do cadastro (não muda o controle: um patrimonial não vira consumo). Recebe todos
-- os campos editáveis; a auditoria guarda só o que mudou.
CREATE FUNCTION core.atualizar_material(
    p_material_tipo_id      integer,
    p_executado_por         integer,
    p_nome                  text,
    p_subcategoria_id       integer,
    p_prazo_devolucao_horas integer,
    p_estoque_minimo        integer,
    p_custo_unitario        numeric,
    p_descricao             text,
    p_ativo                 boolean
) RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_nome  text := core._texto(p_nome);
    v_antes core.material_tipo%ROWTYPE;
    v_saldo core.saldo_consumo%ROWTYPE;
    v_min_antes integer;
    v_mudou jsonb := '{}'::jsonb;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    SELECT * INTO v_antes FROM core.material_tipo WHERE id = p_material_tipo_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Material % não existe.', p_material_tipo_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_nome IS NULL THEN
        RAISE EXCEPTION 'Informe o nome do material.' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.material_tipo
               WHERE lower(nome) = lower(v_nome) AND id <> p_material_tipo_id) THEN
        RAISE EXCEPTION 'Já existe um material chamado "%".', v_nome USING ERRCODE = 'ALM11';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.subcategoria WHERE id = p_subcategoria_id) THEN
        RAISE EXCEPTION 'Subcategoria % não existe.', p_subcategoria_id USING ERRCODE = 'ALM09';
    END IF;
    IF p_custo_unitario IS NULL OR p_custo_unitario < 0 THEN
        RAISE EXCEPTION 'Valor unitário não pode ser negativo.' USING ERRCODE = 'ALM10';
    END IF;
    IF p_ativo IS NULL THEN
        RAISE EXCEPTION 'Informe se o material está ativo.' USING ERRCODE = 'ALM10';
    END IF;
    IF p_estoque_minimo IS NOT NULL AND p_estoque_minimo < 0 THEN
        RAISE EXCEPTION 'Estoque mínimo não pode ser negativo.' USING ERRCODE = 'ALM10';
    END IF;

    IF v_antes.controle = 'SERIAL' THEN
        IF p_prazo_devolucao_horas IS NOT NULL
           AND p_prazo_devolucao_horas NOT BETWEEN 1 AND 8760 THEN
            RAISE EXCEPTION 'Prazo de devolução deve ficar entre 1 e 8760 horas.'
                USING ERRCODE = 'ALM10';
        END IF;
        v_min_antes := v_antes.estoque_minimo;
    ELSE
        IF p_prazo_devolucao_horas IS NOT NULL THEN
            RAISE EXCEPTION 'Material de consumo não é cautelado (não tem prazo de devolução).'
                USING ERRCODE = 'ALM10';
        END IF;
        IF p_estoque_minimo IS NULL THEN
            RAISE EXCEPTION 'Material de consumo exige estoque mínimo.' USING ERRCODE = 'ALM10';
        END IF;
        SELECT * INTO v_saldo FROM core.saldo_consumo
        WHERE material_tipo_id = p_material_tipo_id FOR UPDATE;
        IF FOUND THEN
            IF p_estoque_minimo > v_saldo.estoque_maximo THEN
                RAISE EXCEPTION 'Estoque mínimo (%) acima do máximo (%).',
                    p_estoque_minimo, v_saldo.estoque_maximo USING ERRCODE = 'ALM10';
            END IF;
            v_min_antes := v_saldo.estoque_minimo;
            UPDATE core.saldo_consumo SET estoque_minimo = p_estoque_minimo
            WHERE material_tipo_id = p_material_tipo_id;
        END IF;
    END IF;

    UPDATE core.material_tipo
    SET nome = v_nome,
        subcategoria_id = p_subcategoria_id,
        prazo_devolucao_horas = p_prazo_devolucao_horas,
        estoque_minimo = CASE WHEN controle = 'SERIAL' THEN p_estoque_minimo END,
        custo_unitario = p_custo_unitario,
        descricao = core._texto(p_descricao),
        ativo = p_ativo
    WHERE id = p_material_tipo_id;

    SELECT coalesce(jsonb_object_agg(chave, jsonb_build_object('antes', antes, 'depois', depois)),
                    '{}'::jsonb)
    INTO v_mudou
    FROM (VALUES
        ('nome', to_jsonb(v_antes.nome::text), to_jsonb(v_nome)),
        ('subcategoria_id', to_jsonb(v_antes.subcategoria_id), to_jsonb(p_subcategoria_id)),
        ('prazo_devolucao_horas', to_jsonb(v_antes.prazo_devolucao_horas),
                                  to_jsonb(p_prazo_devolucao_horas)),
        ('estoque_minimo', to_jsonb(v_min_antes), to_jsonb(p_estoque_minimo)),
        ('custo_unitario', to_jsonb(v_antes.custo_unitario), to_jsonb(p_custo_unitario)),
        ('descricao', to_jsonb(v_antes.descricao), to_jsonb(core._texto(p_descricao))),
        ('ativo', to_jsonb(v_antes.ativo), to_jsonb(p_ativo))
    ) AS c(chave, antes, depois)
    WHERE antes IS DISTINCT FROM depois;

    IF v_mudou <> '{}'::jsonb THEN
        PERFORM core._auditar(p_executado_por, 'ATUALIZAR', 'MATERIAL', p_material_tipo_id,
                              v_mudou);
    END IF;
END;
$$;

-- Incorpora N unidades de um material patrimonial numa transação: BMPs sequenciais, a
-- partir do maior já usado. Estado de chegada: BOM -> DISPONIVEL; AVARIADO ->
-- EM_MANUTENCAO; INSERVIVEL -> BAIXA_PENDENTE (os dois últimos exigem observação, como na
-- devolução). Devolve os ids das unidades.
CREATE FUNCTION core.registrar_entrada_lote(
    p_material_tipo_id integer,
    p_quantidade       integer,
    p_local_id         integer,
    p_executado_por    integer,
    p_estado           text DEFAULT 'BOM',
    p_observacao       text DEFAULT NULL,
    p_documento_ref    text DEFAULT NULL
) RETURNS integer[]
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_status   text;
    v_proximo  integer;
    v_unidade  integer;
    v_ids      integer[] := '{}';
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR', 'ESTOQUISTA']);

    IF p_quantidade IS NULL OR p_quantidade NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'Quantidade deve ficar entre 1 e 500 (recebido: %).',
            coalesce(p_quantidade::text, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
    v_status := CASE p_estado
                    WHEN 'BOM'        THEN 'DISPONIVEL'
                    WHEN 'AVARIADO'   THEN 'EM_MANUTENCAO'
                    WHEN 'INSERVIVEL' THEN 'BAIXA_PENDENTE'
                END;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Estado inválido: % (use BOM, AVARIADO ou INSERVIVEL).',
            coalesce(p_estado, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
    IF p_estado <> 'BOM' AND core._texto(p_observacao) IS NULL THEN
        RAISE EXCEPTION 'Material % na entrada exige observação descrevendo o problema.',
            p_estado USING ERRCODE = 'ALM10';
    END IF;
    -- Sem isto, um local inexistente só apareceria como erro de chave estrangeira.
    IF NOT EXISTS (SELECT 1 FROM core.local_armazenagem WHERE id = p_local_id) THEN
        RAISE EXCEPTION 'Local % não existe.', p_local_id USING ERRCODE = 'ALM09';
    END IF;

    -- Duas entradas simultâneas não podem calcular o mesmo "próximo BMP".
    PERFORM pg_advisory_xact_lock(hashtext('core.unidade_patrimonial.bmp'));
    SELECT coalesce(max(bmp::integer), 999999) + 1 INTO v_proximo
    FROM core.unidade_patrimonial;
    IF v_proximo + p_quantidade - 1 > 9999999 THEN
        RAISE EXCEPTION 'Números de BMP esgotados.' USING ERRCODE = 'ALM10';
    END IF;

    FOR i IN 0 .. p_quantidade - 1 LOOP
        v_unidade := core.registrar_entrada_unidade(
            p_material_tipo_id => p_material_tipo_id,
            p_local_id         => p_local_id,
            p_executado_por    => p_executado_por,
            p_bmp              => lpad((v_proximo + i)::text, 7, '0'),
            p_ocorrida_em      => now(),
            p_documento_ref    => coalesce(core._texto(p_documento_ref), 'Entrada em lote'),
            p_observacao       => p_observacao);
        IF v_status <> 'DISPONIVEL' THEN
            PERFORM core.alterar_status_unidade(
                p_unidade_id    => v_unidade,
                p_novo_status   => v_status,
                p_executado_por => p_executado_por,
                p_justificativa => 'Chegou ' || lower(p_estado) || ': '
                                   || core._texto(p_observacao),
                p_ocorrida_em   => now());
        END IF;
        v_ids := v_ids || v_unidade;
    END LOOP;
    RETURN v_ids;
END;
$$;
""".replace("{definer}", DEFINER)

PESSOAS = r"""
CREATE FUNCTION core._validar_pessoa(
    p_nome text, p_nome_guerra text, p_posto text, p_setor_id integer, p_ignorar integer
) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF core._texto(p_nome) IS NULL THEN
        RAISE EXCEPTION 'Informe o nome completo.' USING ERRCODE = 'ALM10';
    END IF;
    IF core._texto(p_nome_guerra) IS NULL OR length(core._texto(p_nome_guerra)) > 30 THEN
        RAISE EXCEPTION 'Informe o nome de guerra (até 30 caracteres).' USING ERRCODE = 'ALM10';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.posto_graduacao WHERE sigla = p_posto) THEN
        RAISE EXCEPTION 'Posto/graduação inválido: %.', coalesce(p_posto, 'NULL')
            USING ERRCODE = 'ALM10';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.setor WHERE id = p_setor_id) THEN
        RAISE EXCEPTION 'Setor % não existe.', p_setor_id USING ERRCODE = 'ALM09';
    END IF;
    IF EXISTS (SELECT 1 FROM core.pessoa
               WHERE lower(nome_guerra) = lower(core._texto(p_nome_guerra))
                 AND data_saida IS NULL AND id IS DISTINCT FROM p_ignorar) THEN
        RAISE EXCEPTION 'Já há um militar na unidade com o nome de guerra "%".',
            core._texto(p_nome_guerra) USING ERRCODE = 'ALM11';
    END IF;
END;
$$;

CREATE FUNCTION core.cadastrar_pessoa(
    p_matricula     text,
    p_nome          text,
    p_nome_guerra   text,
    p_posto         text,
    p_setor_id      integer,
    p_executado_por integer,
    p_data_entrada  date DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_matricula text := core._texto(p_matricula);
    v_entrada   date := coalesce(p_data_entrada, core.data_local(now()));
    v_id        integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    IF v_matricula IS NULL OR v_matricula !~ '^[0-9]{7}$' THEN
        RAISE EXCEPTION 'Matrícula deve ter 7 dígitos.' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.pessoa WHERE matricula = v_matricula) THEN
        RAISE EXCEPTION 'Já existe um militar com a matrícula %.', v_matricula
            USING ERRCODE = 'ALM11';
    END IF;
    IF v_entrada > core.data_local(now()) THEN
        RAISE EXCEPTION 'Data de apresentação não pode ser futura.' USING ERRCODE = 'ALM10';
    END IF;
    PERFORM core._validar_pessoa(p_nome, p_nome_guerra, p_posto, p_setor_id, NULL);

    INSERT INTO core.pessoa (matricula, nome, setor_id, data_entrada, posto_graduacao,
                             nome_guerra)
    VALUES (v_matricula, core._texto(p_nome), p_setor_id, v_entrada, p_posto,
            core._texto(p_nome_guerra))
    RETURNING id INTO v_id;
    PERFORM core._auditar(p_executado_por, 'CADASTRAR', 'PESSOA', v_id,
        jsonb_build_object('matricula', v_matricula, 'posto', p_posto,
                           'nome_guerra', core._texto(p_nome_guerra)));
    RETURN v_id;
END;
$$;

CREATE FUNCTION core.atualizar_pessoa(
    p_pessoa_id     integer,
    p_nome          text,
    p_nome_guerra   text,
    p_posto         text,
    p_setor_id      integer,
    p_executado_por integer
) RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_antes core.pessoa%ROWTYPE;
    v_mudou jsonb;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    SELECT * INTO v_antes FROM core.pessoa WHERE id = p_pessoa_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Militar % não existe.', p_pessoa_id USING ERRCODE = 'ALM09';
    END IF;
    PERFORM core._validar_pessoa(p_nome, p_nome_guerra, p_posto, p_setor_id, p_pessoa_id);

    UPDATE core.pessoa
    SET nome = core._texto(p_nome), nome_guerra = core._texto(p_nome_guerra),
        posto_graduacao = p_posto, setor_id = p_setor_id
    WHERE id = p_pessoa_id;

    SELECT coalesce(jsonb_object_agg(chave, jsonb_build_object('antes', antes, 'depois', depois)),
                    '{}'::jsonb)
    INTO v_mudou
    FROM (VALUES
        ('nome', to_jsonb(v_antes.nome::text), to_jsonb(core._texto(p_nome))),
        ('nome_guerra', to_jsonb(v_antes.nome_guerra::text), to_jsonb(core._texto(p_nome_guerra))),
        ('posto', to_jsonb(v_antes.posto_graduacao), to_jsonb(p_posto)),
        ('setor_id', to_jsonb(v_antes.setor_id), to_jsonb(p_setor_id))
    ) AS c(chave, antes, depois)
    WHERE antes IS DISTINCT FROM depois;
    IF v_mudou <> '{}'::jsonb THEN
        PERFORM core._auditar(p_executado_por, 'ATUALIZAR', 'PESSOA', p_pessoa_id, v_mudou);
    END IF;
END;
$$;

-- Saída da unidade (transferência, licenciamento). Recusada se o militar ainda tem
-- material em posse. O usuário do sistema ligado a ele (se houver) é desativado e perde as
-- sessões abertas.
CREATE FUNCTION core.registrar_saida_pessoa(
    p_pessoa_id     integer,
    p_data_saida    date,
    p_executado_por integer
) RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_entrada date;
    v_saida   date;
    v_posse   integer;
    v_usuario integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    SELECT data_entrada, data_saida INTO v_entrada, v_saida
    FROM core.pessoa WHERE id = p_pessoa_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Militar % não existe.', p_pessoa_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_saida IS NOT NULL THEN
        RAISE EXCEPTION 'A saída deste militar já foi registrada (%).', v_saida
            USING ERRCODE = 'ALM02';
    END IF;
    IF p_data_saida IS NULL OR p_data_saida < v_entrada THEN
        RAISE EXCEPTION 'Data de saída inválida (precisa ser a partir de %).', v_entrada
            USING ERRCODE = 'ALM10';
    END IF;
    SELECT id INTO v_usuario FROM core.usuario WHERE pessoa_id = p_pessoa_id;
    IF v_usuario = p_executado_por THEN
        RAISE EXCEPTION 'Você não pode registrar a sua própria saída.' USING ERRCODE = 'ALM10';
    END IF;
    SELECT count(*) INTO v_posse FROM core.unidade_patrimonial
    WHERE detentor_id = p_pessoa_id AND status = 'CAUTELADA';
    IF v_posse > 0 THEN
        RAISE EXCEPTION 'O militar ainda tem % unidade(s) em posse. Receba a devolução antes.',
            v_posse USING ERRCODE = 'ALM02';
    END IF;

    UPDATE core.pessoa SET data_saida = p_data_saida WHERE id = p_pessoa_id;
    IF v_usuario IS NOT NULL THEN
        UPDATE core.usuario SET ativo = false WHERE id = v_usuario;
        DELETE FROM app.sessao WHERE usuario_id = v_usuario;
    END IF;
    PERFORM core._auditar(p_executado_por, 'REGISTRAR_SAIDA', 'PESSOA', p_pessoa_id,
        jsonb_build_object('data_saida', p_data_saida, 'usuario_desativado', v_usuario));
END;
$$;
""".replace("{definer}", DEFINER)

USUARIOS = r"""
CREATE FUNCTION core._exigir_um_administrador_ativo() RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM core.usuario WHERE perfil = 'ADMINISTRADOR' AND ativo) THEN
        RAISE EXCEPTION 'O sistema precisa de pelo menos um administrador ativo.'
            USING ERRCODE = 'ALM02';
    END IF;
END;
$$;

CREATE FUNCTION core.cadastrar_usuario(
    p_pessoa_id     integer,
    p_login         text,
    p_perfil        text,
    p_executado_por integer
) RETURNS integer
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_login text := lower(core._texto(p_login));
    v_saida date;
    v_id    integer;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    SELECT data_saida INTO v_saida FROM core.pessoa WHERE id = p_pessoa_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Militar % não existe.', p_pessoa_id USING ERRCODE = 'ALM09';
    END IF;
    IF v_saida IS NOT NULL THEN
        RAISE EXCEPTION 'O militar já saiu da unidade.' USING ERRCODE = 'ALM03';
    END IF;
    IF EXISTS (SELECT 1 FROM core.usuario WHERE pessoa_id = p_pessoa_id) THEN
        RAISE EXCEPTION 'Este militar já tem usuário no sistema.' USING ERRCODE = 'ALM11';
    END IF;
    IF v_login IS NULL OR v_login !~ '^[a-z][a-z0-9._]{2,31}$' THEN
        RAISE EXCEPTION 'Login inválido: de 3 a 32 caracteres, começando por letra (letras, '
                        'números, ponto e sublinhado).' USING ERRCODE = 'ALM10';
    END IF;
    IF EXISTS (SELECT 1 FROM core.usuario WHERE login = v_login) THEN
        RAISE EXCEPTION 'O login "%" já está em uso.', v_login USING ERRCODE = 'ALM11';
    END IF;
    IF p_perfil IS NULL OR p_perfil NOT IN ('ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA',
                                            'CONSULTA') THEN
        RAISE EXCEPTION 'Perfil inválido: %.', coalesce(p_perfil, 'NULL') USING ERRCODE = 'ALM10';
    END IF;

    INSERT INTO core.usuario (pessoa_id, login, perfil) VALUES (p_pessoa_id, v_login, p_perfil)
    RETURNING id INTO v_id;
    PERFORM core._auditar(p_executado_por, 'CADASTRAR', 'USUARIO', v_id,
                          jsonb_build_object('login', v_login, 'perfil', p_perfil,
                                             'pessoa_id', p_pessoa_id));
    RETURN v_id;
END;
$$;

-- Perfil e ativação. Mudar o perfil ou desativar encerra as sessões abertas do usuário:
-- a permissão nova vale na hora, e não só no próximo login.
CREATE FUNCTION core.alterar_usuario(
    p_usuario_id    integer,
    p_perfil        text,
    p_ativo         boolean,
    p_executado_por integer
) RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_antes core.usuario%ROWTYPE;
    v_saida date;
BEGIN
    PERFORM core._exigir_perfil(p_executado_por, ARRAY['ADMINISTRADOR']);
    -- Trava todos os administradores: duas alterações simultâneas não podem, cada uma,
    -- achar que "ainda sobra o outro" e deixar o sistema sem nenhum.
    PERFORM 1 FROM core.usuario WHERE perfil = 'ADMINISTRADOR' FOR UPDATE;
    SELECT * INTO v_antes FROM core.usuario WHERE id = p_usuario_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Usuário % não existe.', p_usuario_id USING ERRCODE = 'ALM09';
    END IF;
    IF p_perfil IS NULL OR p_perfil NOT IN ('ADMINISTRADOR', 'ESTOQUISTA', 'EQUIPAMENTISTA',
                                            'CONSULTA') THEN
        RAISE EXCEPTION 'Perfil inválido: %.', coalesce(p_perfil, 'NULL') USING ERRCODE = 'ALM10';
    END IF;
    IF p_ativo IS NULL THEN
        RAISE EXCEPTION 'Informe se o usuário está ativo.' USING ERRCODE = 'ALM10';
    END IF;
    IF p_usuario_id = p_executado_por AND (p_perfil <> 'ADMINISTRADOR' OR NOT p_ativo) THEN
        RAISE EXCEPTION 'Você não pode remover o seu próprio acesso de administrador.'
            USING ERRCODE = 'ALM10';
    END IF;
    IF p_ativo AND NOT v_antes.ativo THEN
        SELECT data_saida INTO v_saida FROM core.pessoa WHERE id = v_antes.pessoa_id;
        IF v_saida IS NOT NULL THEN
            RAISE EXCEPTION 'O militar já saiu da unidade: o usuário não pode ser reativado.'
                USING ERRCODE = 'ALM03';
        END IF;
    END IF;

    UPDATE core.usuario SET perfil = p_perfil, ativo = p_ativo WHERE id = p_usuario_id;
    PERFORM core._exigir_um_administrador_ativo();
    IF p_perfil <> v_antes.perfil OR p_ativo <> v_antes.ativo THEN
        DELETE FROM app.sessao WHERE usuario_id = p_usuario_id;
        PERFORM core._auditar(p_executado_por, 'ALTERAR', 'USUARIO', p_usuario_id,
            jsonb_build_object(
                'perfil', jsonb_build_object('antes', v_antes.perfil, 'depois', p_perfil),
                'ativo', jsonb_build_object('antes', v_antes.ativo, 'depois', p_ativo)));
    END IF;
END;
$$;
""".replace("{definer}", DEFINER)

# Funções da aplicação: o primeiro parâmetro é o hash (SHA-256) do token da sessão. Quem
# executa é sempre o dono da sessão, nunca um id vindo de fora.
APP = r"""
CREATE FUNCTION app._usuario(p_token_hash bytea) RETURNS integer
LANGUAGE plpgsql STABLE {definer} AS $$
DECLARE
    v_usuario integer;
BEGIN
    SELECT s.usuario_id INTO v_usuario
    FROM app.sessao s
    JOIN core.usuario u ON u.id = s.usuario_id
    WHERE s.token_hash = p_token_hash AND s.expira_em > now() AND u.ativo;
    IF v_usuario IS NULL THEN
        RAISE EXCEPTION 'Sessão inválida ou expirada. Entre de novo.' USING ERRCODE = 'ALM13';
    END IF;
    RETURN v_usuario;
END;
$$;

CREATE FUNCTION app.retirar(
    p_token_hash bytea, p_material_tipo_id integer, p_quantidade integer, p_pessoa_id integer,
    p_operacao uuid, p_estado_retirada text, p_finalidade text, p_observacao text,
    p_unidades integer[]
) RETURNS uuid
LANGUAGE sql {definer} AS $$
    SELECT core.registrar_retirada_lote(
        p_material_tipo_id => p_material_tipo_id, p_quantidade => p_quantidade,
        p_pessoa_id => p_pessoa_id, p_executado_por => app._usuario(p_token_hash),
        p_operacao => p_operacao, p_estado_retirada => p_estado_retirada,
        p_finalidade => p_finalidade, p_observacao => p_observacao, p_unidades => p_unidades);
$$;

CREATE FUNCTION app.devolver(
    p_token_hash bytea, p_unidades integer[], p_pessoa_id integer, p_estado text,
    p_observacao text, p_operacao uuid
) RETURNS uuid
LANGUAGE sql {definer} AS $$
    SELECT core.registrar_devolucao_lote(
        p_unidades => p_unidades, p_pessoa_id => p_pessoa_id,
        p_executado_por => app._usuario(p_token_hash), p_estado => p_estado,
        p_observacao => p_observacao, p_operacao => p_operacao);
$$;

CREATE FUNCTION app.entrada_lote(
    p_token_hash bytea, p_material_tipo_id integer, p_quantidade integer, p_local_id integer,
    p_estado text, p_observacao text, p_documento_ref text
) RETURNS integer[]
LANGUAGE sql {definer} AS $$
    SELECT core.registrar_entrada_lote(
        p_material_tipo_id => p_material_tipo_id, p_quantidade => p_quantidade,
        p_local_id => p_local_id, p_executado_por => app._usuario(p_token_hash),
        p_estado => p_estado, p_observacao => p_observacao, p_documento_ref => p_documento_ref);
$$;

CREATE FUNCTION app.entrada_consumo(
    p_token_hash bytea, p_material_tipo_id integer, p_quantidade integer,
    p_documento_ref text, p_observacao text
) RETURNS bigint
LANGUAGE sql {definer} AS $$
    SELECT core.registrar_entrada_consumo(
        p_material_tipo_id => p_material_tipo_id, p_quantidade => p_quantidade,
        p_executado_por => app._usuario(p_token_hash), p_documento_ref => p_documento_ref,
        p_observacao => p_observacao);
$$;

CREATE FUNCTION app.ajustar_consumo(
    p_token_hash bytea, p_material_tipo_id integer, p_quantidade_contada integer,
    p_justificativa text
) RETURNS bigint
LANGUAGE sql {definer} AS $$
    SELECT core.registrar_ajuste_consumo(
        p_material_tipo_id => p_material_tipo_id, p_quantidade_contada => p_quantidade_contada,
        p_executado_por => app._usuario(p_token_hash), p_justificativa => p_justificativa);
$$;

CREATE FUNCTION app.alterar_status_unidade(
    p_token_hash bytea, p_unidade_id integer, p_novo_status text, p_justificativa text,
    p_bmp text
) RETURNS bigint
LANGUAGE sql {definer} AS $$
    SELECT core.alterar_status_unidade(
        p_unidade_id => p_unidade_id, p_novo_status => p_novo_status,
        p_executado_por => app._usuario(p_token_hash), p_justificativa => p_justificativa,
        p_bmp => p_bmp);
$$;

CREATE FUNCTION app.cadastrar_categoria(p_token_hash bytea, p_nome text) RETURNS integer
LANGUAGE sql {definer} AS $$
    SELECT core.cadastrar_categoria(p_nome, app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.renomear_categoria(p_token_hash bytea, p_categoria_id integer, p_nome text)
RETURNS void
LANGUAGE sql {definer} AS $$
    SELECT core.renomear_categoria(p_categoria_id, p_nome, app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.cadastrar_subcategoria(p_token_hash bytea, p_categoria_id integer,
                                           p_nome text) RETURNS integer
LANGUAGE sql {definer} AS $$
    SELECT core.cadastrar_subcategoria(p_categoria_id, p_nome, app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.renomear_subcategoria(p_token_hash bytea, p_subcategoria_id integer,
                                          p_nome text) RETURNS void
LANGUAGE sql {definer} AS $$
    SELECT core.renomear_subcategoria(p_subcategoria_id, p_nome, app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.cadastrar_material(
    p_token_hash bytea, p_nome text, p_subcategoria_id integer, p_controle text,
    p_unidade_medida text, p_prazo_devolucao_horas integer, p_estoque_minimo integer,
    p_estoque_maximo integer, p_local_id integer, p_custo_unitario numeric, p_descricao text
) RETURNS integer
LANGUAGE sql {definer} AS $$
    SELECT core.cadastrar_material(
        p_nome => p_nome, p_subcategoria_id => p_subcategoria_id, p_controle => p_controle,
        p_executado_por => app._usuario(p_token_hash), p_unidade_medida => p_unidade_medida,
        p_prazo_devolucao_horas => p_prazo_devolucao_horas, p_estoque_minimo => p_estoque_minimo,
        p_estoque_maximo => p_estoque_maximo, p_local_id => p_local_id,
        p_custo_unitario => p_custo_unitario, p_descricao => p_descricao);
$$;

CREATE FUNCTION app.atualizar_material(
    p_token_hash bytea, p_material_tipo_id integer, p_nome text, p_subcategoria_id integer,
    p_prazo_devolucao_horas integer, p_estoque_minimo integer, p_custo_unitario numeric,
    p_descricao text, p_ativo boolean
) RETURNS void
LANGUAGE sql {definer} AS $$
    SELECT core.atualizar_material(
        p_material_tipo_id => p_material_tipo_id, p_executado_por => app._usuario(p_token_hash),
        p_nome => p_nome, p_subcategoria_id => p_subcategoria_id,
        p_prazo_devolucao_horas => p_prazo_devolucao_horas, p_estoque_minimo => p_estoque_minimo,
        p_custo_unitario => p_custo_unitario, p_descricao => p_descricao, p_ativo => p_ativo);
$$;

CREATE FUNCTION app.cadastrar_pessoa(
    p_token_hash bytea, p_matricula text, p_nome text, p_nome_guerra text, p_posto text,
    p_setor_id integer, p_data_entrada date
) RETURNS integer
LANGUAGE sql {definer} AS $$
    SELECT core.cadastrar_pessoa(
        p_matricula => p_matricula, p_nome => p_nome, p_nome_guerra => p_nome_guerra,
        p_posto => p_posto, p_setor_id => p_setor_id,
        p_executado_por => app._usuario(p_token_hash), p_data_entrada => p_data_entrada);
$$;

CREATE FUNCTION app.atualizar_pessoa(
    p_token_hash bytea, p_pessoa_id integer, p_nome text, p_nome_guerra text, p_posto text,
    p_setor_id integer
) RETURNS void
LANGUAGE sql {definer} AS $$
    SELECT core.atualizar_pessoa(p_pessoa_id, p_nome, p_nome_guerra, p_posto, p_setor_id,
                                 app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.registrar_saida_pessoa(p_token_hash bytea, p_pessoa_id integer,
                                           p_data_saida date) RETURNS void
LANGUAGE sql {definer} AS $$
    SELECT core.registrar_saida_pessoa(p_pessoa_id, p_data_saida, app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.cadastrar_usuario(p_token_hash bytea, p_pessoa_id integer, p_login text,
                                      p_perfil text) RETURNS integer
LANGUAGE sql {definer} AS $$
    SELECT core.cadastrar_usuario(p_pessoa_id, p_login, p_perfil, app._usuario(p_token_hash));
$$;

CREATE FUNCTION app.alterar_usuario(p_token_hash bytea, p_usuario_id integer, p_perfil text,
                                    p_ativo boolean) RETURNS void
LANGUAGE sql {definer} AS $$
    SELECT core.alterar_usuario(p_usuario_id, p_perfil, p_ativo, app._usuario(p_token_hash));
$$;

-- Senha definida pelo administrador (cadastro ou "esqueci a senha"). O hash scrypt é
-- calculado na API; o CHECK da tabela recusa qualquer outra coisa. As sessões abertas do
-- usuário são encerradas (menos a de quem está trocando, se for a própria).
CREATE FUNCTION app.definir_senha(p_token_hash bytea, p_usuario_id integer,
                                  p_senha_hash text) RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_executor integer := app._usuario(p_token_hash);
BEGIN
    PERFORM core._exigir_perfil(v_executor, ARRAY['ADMINISTRADOR']);
    IF NOT EXISTS (SELECT 1 FROM core.usuario WHERE id = p_usuario_id) THEN
        RAISE EXCEPTION 'Usuário % não existe.', p_usuario_id USING ERRCODE = 'ALM09';
    END IF;
    INSERT INTO app.credencial (usuario_id, senha_hash) VALUES (p_usuario_id, p_senha_hash)
    ON CONFLICT (usuario_id) DO UPDATE
        SET senha_hash = EXCLUDED.senha_hash, atualizada_em = now();
    DELETE FROM app.sessao WHERE usuario_id = p_usuario_id AND token_hash <> p_token_hash;
    PERFORM core._auditar(v_executor, 'DEFINIR_SENHA', 'USUARIO', p_usuario_id);
END;
$$;

-- Troca da própria senha (qualquer perfil). A API confere a senha atual antes de chamar.
CREATE FUNCTION app.trocar_minha_senha(p_token_hash bytea, p_senha_hash text) RETURNS void
LANGUAGE plpgsql {definer} AS $$
DECLARE
    v_usuario integer := app._usuario(p_token_hash);
BEGIN
    INSERT INTO app.credencial (usuario_id, senha_hash) VALUES (v_usuario, p_senha_hash)
    ON CONFLICT (usuario_id) DO UPDATE
        SET senha_hash = EXCLUDED.senha_hash, atualizada_em = now();
    DELETE FROM app.sessao WHERE usuario_id = v_usuario AND token_hash <> p_token_hash;
    PERFORM core._auditar(v_usuario, 'TROCAR_SENHA', 'USUARIO', v_usuario);
END;
$$;
""".replace("{definer}", DEFINER)

FUNCOES_CORE = (
    "core.cadastrar_categoria",
    "core.renomear_categoria",
    "core.cadastrar_subcategoria",
    "core.renomear_subcategoria",
    "core.cadastrar_material",
    "core.atualizar_material",
    "core.registrar_entrada_lote",
    "core.cadastrar_pessoa",
    "core.atualizar_pessoa",
    "core.registrar_saida_pessoa",
    "core.cadastrar_usuario",
    "core.alterar_usuario",
    "core._auditar",
    "core._validar_pessoa",
    "core._exigir_um_administrador_ativo",
    "core.tg_auditoria_imutavel",
)

FUNCOES_APP = (
    "app.retirar",
    "app.devolver",
    "app.entrada_lote",
    "app.entrada_consumo",
    "app.ajustar_consumo",
    "app.alterar_status_unidade",
    "app.cadastrar_categoria",
    "app.renomear_categoria",
    "app.cadastrar_subcategoria",
    "app.renomear_subcategoria",
    "app.cadastrar_material",
    "app.atualizar_material",
    "app.cadastrar_pessoa",
    "app.atualizar_pessoa",
    "app.registrar_saida_pessoa",
    "app.cadastrar_usuario",
    "app.alterar_usuario",
    "app.definir_senha",
    "app.trocar_minha_senha",
)

PERMISSOES = r"""
REVOKE EXECUTE ON FUNCTION {core} FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app._usuario, {app} FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        -- A API deixa de chamar as funções do core: só as da aplicação, com a sessão.
        REVOKE EXECUTE ON FUNCTION core.registrar_retirada_unidade,
                                   core.registrar_devolucao_unidade,
                                   core.registrar_retirada_lote,
                                   core.registrar_devolucao_lote
            FROM almox_aplicacao;
        GRANT EXECUTE ON FUNCTION {app} TO almox_aplicacao;
        GRANT SELECT ON core.auditoria TO almox_aplicacao;
    END IF;
END;
$$;
""".replace("{core}", ", ".join(FUNCOES_CORE)).replace("{app}", ", ".join(FUNCOES_APP))

PERMISSOES_ANTIGAS = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'almox_aplicacao') THEN
        GRANT EXECUTE ON FUNCTION core.registrar_retirada_unidade,
                                  core.registrar_devolucao_unidade,
                                  core.registrar_retirada_lote,
                                  core.registrar_devolucao_lote
            TO almox_aplicacao;
    END IF;
END;
$$;
"""


def upgrade() -> None:
    op.execute(AUDITORIA)
    op.execute(CATEGORIAS)
    op.execute(MATERIAIS)
    op.execute(PESSOAS)
    op.execute(USUARIOS)
    op.execute(APP)
    op.execute(PERMISSOES)


def downgrade() -> None:
    op.execute(PERMISSOES_ANTIGAS)
    op.execute(
        """
        DROP FUNCTION app.trocar_minha_senha(bytea, text);
        DROP FUNCTION app.definir_senha(bytea, integer, text);
        DROP FUNCTION app.alterar_usuario(bytea, integer, text, boolean);
        DROP FUNCTION app.cadastrar_usuario(bytea, integer, text, text);
        DROP FUNCTION app.registrar_saida_pessoa(bytea, integer, date);
        DROP FUNCTION app.atualizar_pessoa(bytea, integer, text, text, text, integer);
        DROP FUNCTION app.cadastrar_pessoa(bytea, text, text, text, text, integer, date);
        DROP FUNCTION app.atualizar_material(
            bytea, integer, text, integer, integer, integer, numeric, text, boolean);
        DROP FUNCTION app.cadastrar_material(
            bytea, text, integer, text, text, integer, integer, integer, integer, numeric, text);
        DROP FUNCTION app.renomear_subcategoria(bytea, integer, text);
        DROP FUNCTION app.cadastrar_subcategoria(bytea, integer, text);
        DROP FUNCTION app.renomear_categoria(bytea, integer, text);
        DROP FUNCTION app.cadastrar_categoria(bytea, text);
        DROP FUNCTION app.alterar_status_unidade(bytea, integer, text, text, text);
        DROP FUNCTION app.ajustar_consumo(bytea, integer, integer, text);
        DROP FUNCTION app.entrada_consumo(bytea, integer, integer, text, text);
        DROP FUNCTION app.entrada_lote(bytea, integer, integer, integer, text, text, text);
        DROP FUNCTION app.devolver(bytea, integer[], integer, text, text, uuid);
        DROP FUNCTION app.retirar(
            bytea, integer, integer, integer, uuid, text, text, text, integer[]);
        DROP FUNCTION app._usuario(bytea);

        DROP FUNCTION core.alterar_usuario(integer, text, boolean, integer);
        DROP FUNCTION core.cadastrar_usuario(integer, text, text, integer);
        DROP FUNCTION core._exigir_um_administrador_ativo();
        DROP FUNCTION core.registrar_saida_pessoa(integer, date, integer);
        DROP FUNCTION core.atualizar_pessoa(integer, text, text, text, integer, integer);
        DROP FUNCTION core.cadastrar_pessoa(text, text, text, text, integer, integer, date);
        DROP FUNCTION core._validar_pessoa(text, text, text, integer, integer);
        DROP FUNCTION core.registrar_entrada_lote(integer, integer, integer, integer, text, text,
                                                  text);
        DROP FUNCTION core.atualizar_material(
            integer, integer, text, integer, integer, integer, numeric, text, boolean);
        DROP FUNCTION core.cadastrar_material(
            text, integer, text, integer, text, integer, integer, integer, integer, numeric, text);
        DROP FUNCTION core.renomear_subcategoria(integer, text, integer);
        DROP FUNCTION core.cadastrar_subcategoria(integer, text, integer);
        DROP FUNCTION core.renomear_categoria(integer, text, integer);
        DROP FUNCTION core.cadastrar_categoria(text, integer);
        DROP FUNCTION core._auditar(integer, text, text, integer, jsonb);
        DROP TABLE core.auditoria;
        DROP FUNCTION core.tg_auditoria_imutavel();
        """
    )
