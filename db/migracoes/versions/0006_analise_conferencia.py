"""schema analise: normalização de texto e conferência da planilha de carga (A1)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24

Conferência = cruzar a planilha (staging, texto como veio) com o cadastro (core, com
integridade garantida). A view `analise.vw_conferencia_planilha` devolve uma linha por
linha da planilha, com a unidade a que ela provavelmente se refere e uma coluna
booleana por tipo de problema encontrado.

Extensões (todas "trusted": o dono do banco instala sem superusuário):
- unaccent: remove acentos ("Rádio" -> "Radio");
- pg_trgm: similaridade por trigramas, para achar nomes com erro de digitação;
- fuzzystrmatch: distância de Levenshtein, para achar BMP com dígito trocado.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NORMALIZACAO = r"""
CREATE SCHEMA analise;
COMMENT ON SCHEMA analise IS 'Consultas e views analíticas (leitura sobre core e staging).';

CREATE EXTENSION unaccent WITH SCHEMA analise;
CREATE EXTENSION pg_trgm WITH SCHEMA analise;
CREATE EXTENSION fuzzystrmatch WITH SCHEMA analise;

-- Abreviações encontradas nas planilhas de carga, e a forma por extenso.
-- (Dicionário montado pelo analista ao olhar os dados: é conhecimento do domínio.)
CREATE TABLE analise.abreviacao (
    abreviada text PRIMARY KEY,
    completa  text NOT NULL
);
INSERT INTO analise.abreviacao (abreviada, completa) VALUES
    ('PORT', 'PORTATIL'), ('DEP', 'DEPOSITO'), ('RES', 'RESERVA'),
    ('EQUIP', 'EQUIPAMENTOS'), ('FERRAM', 'FERRAMENTAS'), ('INST', 'INSTALACOES'),
    ('ADM', 'ADMINISTRATIVAS'), ('INFORM', 'INFORMATICA'), ('EXT', 'EXTENSIVEL'),
    ('RECARREG', 'RECARREGAVEL'), ('SINALIZ', 'SINALIZACAO'), ('MULTIM', 'MULTIMIDIA');

-- Texto normalizado: sem acento, maiúsculas, só letras e dígitos separados por um
-- espaço, abreviações por extenso. "Rádio Port.  VHF RP-100," -> "RADIO PORTATIL VHF RP 100".
-- A abreviação só é expandida quando escrita com ponto ("Port."): sem essa exigência,
-- o fragmento "port" de "2 port as" (texto quebrado na extração) virava "PORTATIL".
-- Por isso a expansão acontece ANTES de tirar a pontuação.
-- STABLE (e não IMMUTABLE) porque consulta a tabela de abreviações.
CREATE FUNCTION analise.normalizar(p_texto text) RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    WITH palavras AS (
        SELECT w.palavra, w.n
        FROM regexp_split_to_table(
                 upper(analise.unaccent('analise.unaccent'::regdictionary, btrim(p_texto))),
                 '\s+') WITH ORDINALITY AS w(palavra, n)
    )
    SELECT nullif(btrim(regexp_replace(
               string_agg(coalesce(a.completa, p.palavra), ' ' ORDER BY p.n),
               '[^A-Z0-9]+', ' ', 'g')), '')
    FROM palavras p
    LEFT JOIN analise.abreviacao a ON p.palavra = a.abreviada || '.'
$$;

-- Chave de comparação: o normalizado sem espaços. Faz "C aixa" (texto quebrado na
-- extração de PDF) e "RP-100"/"RP100" coincidirem com o nome correto.
CREATE FUNCTION analise.chave(p_texto text) RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT replace(analise.normalizar(p_texto), ' ', '')
$$;
"""

VIEW_CONFERENCIA = r"""
CREATE VIEW analise.vw_conferencia_planilha AS
WITH planilha AS (
    SELECT
        p.*,
        analise.normalizar(p.nomenclatura) AS nome_norm,
        analise.chave(p.nomenclatura)      AS nome_chave,
        string_to_array(analise.normalizar(p.nomenclatura), ' ') AS nome_palavras,
        -- Fração das letras que estão em maiúscula (1 = tudo maiúsculo). Uma fração, e
        -- não "tudo", porque uma digitação pode inserir uma minúscula num texto em caixa alta.
        (SELECT count(*) FILTER (WHERE c <> lower(c))::numeric
                / nullif(count(*) FILTER (WHERE c <> lower(c) OR c <> upper(c)), 0)
         FROM regexp_split_to_table(p.nomenclatura, '') AS c) AS maiusculas,
        analise.normalizar(p.local)        AS local_norm,
        -- Linha repetida: mesma combinação de todos os campos. A primeira ocorrência é
        -- a original; as seguintes são duplicatas.
        row_number() OVER (
            PARTITION BY p.bmp, p.nomenclatura, p.numero_serie, p.local, p.situacao
            ORDER BY p.linha
        ) AS ocorrencia
    FROM staging.carga_planilha p
),
catalogo AS (
    SELECT id, codigo, nome,
           analise.normalizar(nome) AS nome_norm,
           analise.chave(nome)      AS nome_chave,
           string_to_array(analise.normalizar(nome), ' ') AS palavras
    FROM core.material_tipo
    WHERE controle = 'SERIAL'
),
-- Material mais parecido com o nome escrito na planilha (similaridade de trigramas
-- sobre a chave sem espaços).
nome_mais_parecido AS (
    SELECT DISTINCT ON (p.linha)
        p.linha, c.id AS material_id, c.codigo, c.nome, c.nome_norm, c.nome_chave, c.palavras,
        analise.similarity(p.nome_chave, c.nome_chave) AS similaridade
    FROM planilha p
    CROSS JOIN catalogo c
    ORDER BY p.linha, analise.similarity(p.nome_chave, c.nome_chave) DESC, c.codigo
),
locais AS (
    SELECT nome, analise.normalizar(nome) AS nome_norm FROM core.local_armazenagem
),
unidade AS (
    SELECT u.id, u.bmp, u.numero_serie, u.status, u.material_tipo_id,
           l.nome AS local_nome, pe.nome AS detentor_nome
    FROM core.unidade_patrimonial u
    JOIN core.local_armazenagem l ON l.id = u.local_id
    LEFT JOIN core.pessoa pe ON pe.id = u.detentor_id
),
-- BMP escrito que não existe: a unidade do mesmo material com o BMP mais próximo
-- (Levenshtein: 1 = um dígito trocado; 2 = dois dígitos vizinhos invertidos).
-- Como os BMPs de um lote são consecutivos, costuma haver vários candidatos a 1-2
-- dígitos; o número de série desempata, MAS só se o dono da série não aparecer na
-- planilha com o próprio BMP. Se aparecer, a série desta linha foi copiada dele (outro
-- erro) e não serve para identificar a unidade.
bmp_vizinho AS (
    SELECT DISTINCT ON (p.linha)
        p.linha, u.id AS unidade_id,
        analise.levenshtein(p.bmp, u.bmp) AS distancia
    FROM planilha p
    JOIN nome_mais_parecido m ON m.linha = p.linha
    JOIN unidade u ON u.material_tipo_id = m.material_id
    WHERE p.bmp IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM unidade x WHERE x.bmp = p.bmp)
      AND analise.levenshtein(p.bmp, u.bmp) <= 2
    ORDER BY p.linha,
             (u.numero_serie IS NOT DISTINCT FROM p.numero_serie
              AND NOT EXISTS (SELECT 1 FROM staging.carga_planilha x WHERE x.bmp = u.bmp)) DESC,
             analise.levenshtein(p.bmp, u.bmp),
             u.bmp
),
-- BMP trocado que caiu em OUTRO BMP existente (os BMPs de um lote são consecutivos,
-- então um dígito trocado costuma coincidir com a unidade vizinha). Sinal: o número de
-- série escrito pertence a outra unidade do mesmo material, cujo BMP está a 1 ou 2
-- dígitos do escrito e que NÃO aparece na planilha com o próprio BMP. Se aparecesse,
-- a linha estaria repetindo a série dela (série copiada), e não errando o BMP.
bmp_trocado_existente AS (
    SELECT DISTINCT ON (p.linha)
        p.linha, dona.id AS unidade_id, analise.levenshtein(p.bmp, dona.bmp) AS distancia
    FROM planilha p
    JOIN nome_mais_parecido m ON m.linha = p.linha
    JOIN unidade exato ON exato.bmp = p.bmp
    JOIN unidade dona ON dona.material_tipo_id = m.material_id
                     AND dona.numero_serie = p.numero_serie
                     AND dona.id <> exato.id
    WHERE analise.levenshtein(p.bmp, dona.bmp) <= 2
      AND NOT EXISTS (SELECT 1 FROM staging.carga_planilha x WHERE x.bmp = dona.bmp)
    ORDER BY p.linha, analise.levenshtein(p.bmp, dona.bmp)
),
-- Unidade a que a linha se refere: a indicada pela série (BMP trocado para outro que
-- existe), senão a do BMP exato, senão a do BMP vizinho (BMP que não existe).
casada AS (
    SELECT p.linha,
           exato.id IS NOT NULL AS bmp_existe,
           t.linha IS NOT NULL  AS bmp_trocado_existente,
           coalesce(t.distancia, v.distancia) AS distancia,
           coalesce(t.unidade_id, exato.id, v.unidade_id) AS unidade_id
    FROM planilha p
    LEFT JOIN unidade exato ON exato.bmp = p.bmp
    LEFT JOIN bmp_trocado_existente t ON t.linha = p.linha
    LEFT JOIN bmp_vizinho v ON v.linha = p.linha
)
SELECT
    p.linha,
    p.bmp, p.nomenclatura, p.numero_serie, p.local, p.situacao,
    m.codigo           AS material_provavel,
    m.nome             AS nome_correto,
    round(m.similaridade::numeric, 3) AS similaridade_nome,
    uc.id              AS unidade_provavel,
    uc.bmp             AS bmp_provavel,

    -- P15: linha repetida
    p.ocorrencia > 1 AS linha_duplicada,

    -- P12: variação de formatação. Cada sinal é independente de erro de digitação,
    -- porque uma mesma linha pode ter os dois.
    p.nomenclatura IS DISTINCT FROM m.nome AND (
           p.maiusculas >= 0.8                                    -- (quase) tudo maiúsculo
        OR (p.nomenclatura = lower(p.nomenclatura) AND m.nome <> lower(m.nome))
        OR (analise.unaccent(p.nomenclatura) = p.nomenclatura
            AND analise.unaccent(m.nome) <> m.nome)                -- acento sumiu
        OR p.nomenclatura ~ '\s{2,}'                              -- espaço duplo
        OR p.nomenclatura ~ '[[:punct:]]\s*$'                     -- pontuação sobrando
        OR p.nomenclatura ~ '[[:alpha:]]\.\s'                     -- abreviação ("Port. ")
        OR length(regexp_replace(rtrim(p.nomenclatura, ',. '), '[^,-]', '', 'g'))
           < length(regexp_replace(m.nome, '[^,-]', '', 'g'))     -- hífen/vírgula sumiu
    ) AS nome_variante,
    -- P13: texto quebrado na extração: duas palavras vizinhas que, juntas, formam uma
    -- palavra do nome correto ("so corros" -> "socorros").
    EXISTS (
        SELECT 1
        FROM generate_subscripts(p.nome_palavras, 1) AS i
        WHERE i < cardinality(p.nome_palavras)
          AND p.nome_palavras[i] || p.nome_palavras[i + 1] = ANY (m.palavras)
          AND NOT (p.nome_palavras[i] = ANY (m.palavras)
                   AND p.nome_palavras[i + 1] = ANY (m.palavras))
    ) AS nome_artefato_extracao,
    -- P13: digitação: mesmo ignorando formato e espaços, o texto continua diferente.
    p.nome_chave IS DISTINCT FROM m.nome_chave AS nome_digitacao,

    -- P14: número de patrimônio
    p.bmp IS NULL AND p.situacao ILIKE '%RECÉM ADQUIRIDO%'     AS bmp_ausente_legitimo,
    p.bmp IS NULL AND p.situacao NOT ILIKE '%RECÉM ADQUIRIDO%' AS bmp_ausente_erro,
    p.bmp IS NOT NULL AND NOT c.bmp_existe                     AS bmp_inexistente,
    c.bmp_trocado_existente                                    AS bmp_trocado_existente,
    c.distancia                                                AS distancia_bmp_vizinho,

    -- P15: número de série diferente do cadastrado para a unidade casada
    uc.id IS NOT NULL AND p.numero_serie IS DISTINCT FROM uc.numero_serie AS serie_divergente,

    -- P16: local escrito fora do padrão (só locais físicos, não "Com fulano")
    p.local NOT LIKE 'Com %'
        AND p.local NOT IN (SELECT nome FROM locais)
        AND p.local_norm IN (SELECT nome_norm FROM locais)       AS local_variante,
    -- P16: planilha diz "no lugar" ou "descarga", o histórico diz que está com alguém
    uc.status = 'CAUTELADA' AND p.situacao = 'LOCALIZADO'      AS divergencia_historico,
    uc.status = 'CAUTELADA' AND p.situacao = 'DESCARGA'        AS baixa_com_detentor,

    uc.status          AS status_no_cadastro,
    uc.local_nome      AS local_no_cadastro,
    uc.detentor_nome   AS detentor_no_cadastro
FROM planilha p
JOIN nome_mais_parecido m ON m.linha = p.linha
JOIN casada c ON c.linha = p.linha
LEFT JOIN unidade uc ON uc.id = c.unidade_id;

COMMENT ON VIEW analise.vw_conferencia_planilha IS
    'Uma linha por linha da planilha de carga, com a unidade provável e os problemas '
    'encontrados (A1). O gabarito (staging.gabarito_erro) serve só para medir o acerto.';
"""


def upgrade() -> None:
    op.execute(NORMALIZACAO)
    op.execute(VIEW_CONFERENCIA)


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW analise.vw_conferencia_planilha;
        DROP FUNCTION analise.chave(text);
        DROP FUNCTION analise.normalizar(text);
        DROP TABLE analise.abreviacao;
        DROP EXTENSION fuzzystrmatch;
        DROP EXTENSION pg_trgm;
        DROP EXTENSION unaccent;
        DROP SCHEMA analise;
        """
    )
