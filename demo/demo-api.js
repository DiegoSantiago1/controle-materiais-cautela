/**
 * Demo sem servidor: responde às chamadas /api da tela no próprio navegador.
 *
 * A tela (web/) é a mesma do sistema; só o fetch é interceptado. Os dados vêm de um retrato
 * do banco da aplicação (demo/exportar_dados.py) e as regras principais do banco são
 * repetidas aqui de forma simplificada (estoque insuficiente, unidade que não está com o
 * militar, estado regular sem observação, transições de situação, duplicados...). O que o
 * visitante faz fica só na memória desta aba: recarregar a página volta ao retrato.
 *
 * As datas do retrato são deslocadas para "agora": a demo sempre parece atualizada.
 */
(() => {
  

  const PASTA = document.currentScript.src.replace(/[^/]*$/, "");
  const fetchOriginal = window.fetch.bind(window);
  const db = {};
  const pronto = fetchOriginal(`${PASTA}dados-demo.json`)
    .then((r) => r.json())
    .then(preparar);

  // ------------------------------------------------------------------ utilidades
  class Erro extends Error {
    constructor(status, mensagem, codigo, campo) {
      super(mensagem);
      Object.assign(this, { status, codigo, campo });
    }
  }
  const invalido = (campo, msg) => new Erro(400, msg, "PEDIDO_INVALIDO", campo);
  const regra = (status, codigo, msg) => new Erro(status, msg, codigo);

  const agora = () => new Date();
  const iso = (d) => new Date(d).toISOString();
  const ms = (t) => (t ? Date.parse(t) : null);
  const semAcento = (s) =>
    String(s ?? "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  const contem = (texto, termo) => semAcento(texto).includes(semAcento(termo));
  const hojeLocal = () => {
    const d = agora();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const inicioDoDia = (data) => new Date(`${data}T00:00:00`).getTime();
  const uuid = () =>
    crypto.randomUUID?.() ??
    "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 3) | 8).toString(16);
    });
  const texto = (v, campo, max = 500) => {
    if (v === undefined || v === null) return null;
    if (typeof v !== "string") throw invalido(campo, `${campo} deve ser texto.`);
    const t = v.trim();
    if (t.length > max) throw invalido(campo, `${campo} aceita até ${max} caracteres.`);
    return t === "" ? null : t;
  };
  const obrigatorio = (v, campo, max) => {
    const t = texto(v, campo, max);
    if (t === null) throw invalido(campo, `Informe ${campo}.`);
    return t;
  };
  const id = (v, campo) => {
    if (!Number.isInteger(v) || v < 1) throw invalido(campo, `${campo} inválido.`);
    return v;
  };
  const inteiro = (v, campo, min, max) => {
    if (!Number.isInteger(v) || v < min || v > max) {
      throw invalido(campo, `${campo} deve ser um número inteiro de ${min} a ${max}.`);
    }
    return v;
  };
  const inteiroOpcional = (v, campo, min, max) =>
    v === undefined || v === null || v === "" ? null : inteiro(v, campo, min, max);
  const umDe = (v, campo, opcoes) => {
    if (!opcoes.includes(v))
      throw invalido(campo, `${campo} deve ser um de: ${opcoes.join(", ")}.`);
    return v;
  };

  // ------------------------------------------------------------------ preparo
  function preparar(d) {
    // Desloca todo o tempo do retrato para que o "agora" dele seja o agora do visitante.
    const desloc = Date.now() - Date.parse(d.gerado_em);
    const mover = (t) => (t ? iso(Date.parse(t) + desloc) : t);
    for (const m of d.movimentacoes) {
      m.ocorrida_em = mover(m.ocorrida_em);
      m.prazo_devolucao = mover(m.prazo_devolucao);
    }
    Object.assign(db, d);
    db.postoPorSigla = new Map(d.postos.map((p) => [p.sigla, p]));
    db.setorPorId = new Map(d.setores.map((s) => [s.id, s]));
    db.localPorId = new Map(d.locais.map((l) => [l.id, l]));
    db.categoriaPorId = new Map(d.categorias.map((c) => [c.id, c]));
    db.subPorId = new Map(d.subcategorias.map((s) => [s.id, s]));
    db.pessoaPorId = new Map(d.pessoas.map((p) => [p.id, p]));
    db.usuarioPorId = new Map(d.usuarios.map((u) => [u.id, u]));
    db.materialPorId = new Map(d.materiais.map((m) => [m.id, m]));
    db.unidadePorId = new Map(d.unidades.map((u) => [u.id, u]));
    db.movsPorUnidade = new Map();
    for (const m of d.movimentacoes) indexar(m);
    db.auditoria = [];
    db.proximo = {
      mov: Math.max(...d.movimentacoes.map((m) => m.id)) + 1,
      unidade: Math.max(...d.unidades.map((u) => u.id)) + 1,
      outro: 100000,
    };
    const rafaela = d.usuarios.find((u) => u.login === "rafaela.01" && u.ativo);
    db.sessao =
      (rafaela ?? d.usuarios.find((u) => u.ativo && u.perfil === "ADMINISTRADOR"))?.id ?? null;
  }

  function indexar(m) {
    if (m.unidade_id == null) return;
    if (!db.movsPorUnidade.has(m.unidade_id)) db.movsPorUnidade.set(m.unidade_id, []);
    db.movsPorUnidade.get(m.unidade_id).push(m);
  }

  // ------------------------------------------------------------------ leituras de apoio
  const pessoa = (pid) => db.pessoaPorId.get(pid);
  const rotulo = (p) => (p ? `${p.posto} ${p.nome_guerra}` : null);
  const executor = (uid) => pessoa(db.usuarioPorId.get(uid)?.pessoa_id);
  const naUnidade = (p) => {
    const hoje = hojeLocal();
    return p.data_entrada <= hoje && (p.data_saida == null || p.data_saida > hoje);
  };
  const emPosseDe = (pid) =>
    db.unidades.filter((u) => u.status === "CAUTELADA" && u.detentor_id === pid).length;
  const subDe = (m) => db.subPorId.get(m.subcategoria_id);
  const categoriaDe = (m) => db.categoriaPorId.get(subDe(m)?.categoria_id);

  function estoque(m) {
    const us = db.unidades.filter((u) => u.material_tipo_id === m.id);
    const conta = (...st) => us.filter((u) => st.includes(u.status)).length;
    const serial = m.controle === "SERIAL";
    const disponivel = serial ? conta("DISPONIVEL") : (m.saldo ?? 0);
    const minimo = serial ? m.estoque_minimo : m.minimo_consumo;
    let situacao = "NORMAL";
    if (disponivel === 0) situacao = "SEM_ESTOQUE";
    else if (minimo > 0 && disponivel <= minimo / 2) situacao = "CRITICO";
    else if (minimo != null && disponivel < minimo) situacao = "ABAIXO_DO_MINIMO";
    const sub = subDe(m);
    const cat = categoriaDe(m);
    return {
      id: m.id,
      codigo: m.codigo,
      nome: m.nome,
      descricao: m.descricao,
      controle: m.controle,
      unidade_medida: m.unidade_medida,
      prazo_devolucao_horas: m.prazo_devolucao_horas,
      custo_unitario: m.custo_unitario,
      ativo: m.ativo,
      categoria_id: cat?.id,
      categoria: cat?.nome,
      subcategoria_id: sub?.id,
      subcategoria: sub?.nome,
      total: serial ? us.filter((u) => u.status !== "BAIXADA").length : (m.saldo ?? 0),
      disponivel,
      em_posse: conta("CAUTELADA"),
      em_manutencao: conta("EM_MANUTENCAO"),
      indisponivel: conta("NAO_LOCALIZADA", "BAIXA_PENDENTE", "AGUARDANDO_TOMBAMENTO"),
      estoque_minimo: minimo,
      situacao,
    };
  }

  const ultimaRetirada = (uid) =>
    (db.movsPorUnidade.get(uid) ?? []).filter((m) => m.tipo === "RETIRADA").at(-1);

  /** Posse agrupada por atendimento (core.vw_posse + GROUP BY da API). */
  function posseAgrupada({ pessoaId = null, soVencidas = false, limite = 2000 } = {}) {
    const grupos = new Map();
    for (const u of db.unidades) {
      if (u.status !== "CAUTELADA" || u.detentor_id == null) continue;
      if (pessoaId !== null && u.detentor_id !== pessoaId) continue;
      const r = ultimaRetirada(u.id);
      if (!r) continue;
      const p = pessoa(u.detentor_id);
      const m = db.materialPorId.get(u.material_tipo_id);
      const chave = `${p.id}|${m.id}|${r.operacao ?? r.id}`;
      let g = grupos.get(chave);
      if (!g) {
        const e = executor(r.executado_por);
        g = {
          pessoa_id: p.id,
          posto: p.posto,
          nome_guerra: p.nome_guerra,
          nome: p.nome,
          matricula: p.matricula,
          setor: db.setorPorId.get(p.setor_id)?.sigla,
          material_tipo_id: m.id,
          codigo: m.codigo,
          material: m.nome,
          categoria: categoriaDe(m)?.nome,
          operacao: r.operacao,
          retirada_em: r.ocorrida_em,
          prazo: r.prazo_devolucao,
          retirada_id: r.id,
          entregue_por_posto: e?.posto,
          entregue_por_guerra: e?.nome_guerra,
          estado_retirada: r.estado_retirada,
          observacao: r.observacao,
          finalidade: r.finalidade,
          quantidade: 0,
          unidades: [],
        };
        grupos.set(chave, g);
      }
      if (ms(r.ocorrida_em) < ms(g.retirada_em)) g.retirada_em = r.ocorrida_em;
      if (ms(r.prazo_devolucao) < ms(g.prazo)) g.prazo = r.prazo_devolucao;
      g.retirada_id = Math.min(g.retirada_id, r.id);
      g.quantidade += 1;
      g.unidades.push({ id: u.id, bmp: u.bmp, numero_serie: u.numero_serie });
    }
    const agoraMs = Date.now();
    let lista = [...grupos.values()].map((g) => {
      g.unidades.sort((a, b) => String(a.bmp).localeCompare(String(b.bmp)));
      g.vencida = g.prazo != null && ms(g.prazo) < agoraMs;
      return g;
    });
    if (soVencidas) lista = lista.filter((g) => g.vencida);
    lista.sort(
      (a, b) =>
        (ms(a.prazo) ?? Infinity) - (ms(b.prazo) ?? Infinity) ||
        a.nome_guerra.localeCompare(b.nome_guerra) ||
        a.material.localeCompare(b.material),
    );
    return lista.slice(0, limite);
  }

  /** Histórico agrupado por atendimento, mais recente primeiro, com cursor. */
  function historico(f = {}) {
    const de = f.de ? inicioDoDia(f.de) : null;
    const ate = f.ate ? inicioDoDia(f.ate) + 86400000 : null;
    const grupos = new Map();
    for (const m of db.movimentacoes) {
      const t = ms(m.ocorrida_em);
      if (de !== null && t < de) continue;
      if (ate !== null && t >= ate) continue;
      if (f.tipo && m.tipo !== f.tipo) continue;
      if (f.material && m.material_tipo_id !== f.material) continue;
      if (f.pessoa && m.pessoa_id !== f.pessoa) continue;
      const chave = `${m.operacao ?? `#${m.id}`}|${m.tipo}|${m.material_tipo_id}|${m.pessoa_id}|${m.executado_por}`;
      let g = grupos.get(chave);
      if (!g) {
        g = { movs: [], m };
        grupos.set(chave, g);
      }
      g.movs.push(m);
    }
    let linhas = [...grupos.values()].map(({ movs, m }) => {
      const mat = db.materialPorId.get(m.material_tipo_id);
      const p = pessoa(m.pessoa_id);
      const e = executor(m.executado_por);
      const primeiro = (campo) => movs.find((x) => x[campo] != null)?.[campo] ?? null;
      const unidade = movs.length === 1 ? db.unidadePorId.get(m.unidade_id) : null;
      return {
        operacao: m.operacao,
        tipo: m.tipo,
        ocorrida_em: movs.reduce(
          (a, x) => (ms(x.ocorrida_em) < ms(a) ? x.ocorrida_em : a),
          m.ocorrida_em,
        ),
        ultimo_id: Math.max(...movs.map((x) => x.id)),
        primeiro_id: Math.min(...movs.map((x) => x.id)),
        material_tipo_id: mat.id,
        codigo: mat.codigo,
        material: mat.nome,
        controle: mat.controle,
        quantidade:
          mat.controle === "CONSUMO"
            ? movs.reduce((a, x) => a + Math.abs(x.variacao ?? 0), 0)
            : movs.length,
        bmp: unidade?.bmp ?? null,
        pessoa_id: p?.id ?? null,
        posto: p?.posto ?? null,
        nome_guerra: p?.nome_guerra ?? null,
        executor_posto: e?.posto,
        executor_guerra: e?.nome_guerra,
        estado_retirada: primeiro("estado_retirada"),
        estado_devolucao: primeiro("estado_devolucao"),
        status_anterior: primeiro("status_anterior"),
        status_novo: primeiro("status_novo"),
        observacao: primeiro("observacao"),
        finalidade: primeiro("finalidade"),
        documento: primeiro("documento_ref"),
        prazo: primeiro("prazo_devolucao"),
        _movs: movs,
      };
    });
    if (f.busca) {
      linhas = linhas.filter(
        (l) =>
          contem(l.material, f.busca) ||
          semAcento(l.codigo).includes(semAcento(f.busca)) ||
          l._movs.some((x) => db.unidadePorId.get(x.unidade_id)?.bmp?.includes(f.busca)) ||
          contem(l.posto ? `${l.posto} ${l.nome_guerra}` : "", f.busca) ||
          contem(pessoa(l.pessoa_id)?.nome, f.busca) ||
          contem(`${l.executor_posto} ${l.executor_guerra}`, f.busca),
      );
    }
    linhas.sort((a, b) => ms(b.ocorrida_em) - ms(a.ocorrida_em) || b.ultimo_id - a.ultimo_id);
    if (f.antes) {
      const em = ms(f.antes.em);
      linhas = linhas.filter(
        (l) => ms(l.ocorrida_em) < em || (ms(l.ocorrida_em) === em && l.ultimo_id < f.antes.id),
      );
    }
    return linhas.slice(0, f.limite ?? 50).map(({ _movs, ...l }) => l);
  }

  function ciclo(operacao, movId) {
    const alvos = db.movimentacoes.filter((m) =>
      operacao ? m.operacao === operacao : m.id === movId,
    );
    const depois = (a, b) =>
      ms(a.ocorrida_em) > ms(b.ocorrida_em) || (a.ocorrida_em === b.ocorrida_em && a.id > b.id);
    const itens = alvos.map((a) => {
      const u = db.unidadePorId.get(a.unidade_id);
      const mat = db.materialPorId.get(a.material_tipo_id);
      const daUnidade = db.movsPorUnidade.get(a.unidade_id) ?? [];
      const ab = daUnidade.filter((r) => r.tipo === "RETIRADA" && !depois(r, a)).at(-1);
      const fe = ab
        ? daUnidade.find(
            (f) => depois(f, ab) && ["DEVOLUCAO", "MUDANCA_STATUS", "ESTORNO"].includes(f.tipo),
          )
        : undefined;
      return {
        id: a.id,
        tipo: a.tipo,
        unidade_id: a.unidade_id,
        bmp: u?.bmp ?? null,
        material: mat.nome,
        codigo: mat.codigo,
        controle: mat.controle,
        quantidade: Math.abs(a.variacao ?? 0),
        ocorrida_em: a.ocorrida_em,
        retirada: {
          id: ab?.id ?? null,
          em: ab?.ocorrida_em ?? null,
          prazo: ab?.prazo_devolucao ?? null,
          estado: ab?.estado_retirada ?? null,
          observacao: ab?.observacao ?? null,
          finalidade: ab?.finalidade ?? null,
          militar: ab ? rotulo(pessoa(ab.pessoa_id)) : null,
          entregue_por: ab ? rotulo(executor(ab.executado_por)) : null,
        },
        fechamento: fe
          ? {
              id: fe.id,
              tipo: fe.tipo,
              em: fe.ocorrida_em,
              estado: fe.estado_devolucao,
              status_novo: fe.status_novo,
              observacao: fe.observacao,
              militar: rotulo(pessoa(fe.pessoa_id)),
              recebido_por: rotulo(executor(fe.executado_por)),
            }
          : null,
      };
    });
    itens.sort((a, b) => (a.bmp ?? "￿").localeCompare(b.bmp ?? "￿") || a.id - b.id);
    return itens;
  }

  // ------------------------------------------------------------------ escrita
  function usuarioAtual() {
    const u = db.usuarioPorId.get(db.sessao);
    if (!u?.ativo) return null;
    const p = pessoa(u.pessoa_id);
    return {
      id: u.id,
      login: u.login,
      perfil: u.perfil,
      nome: p.nome,
      posto: p.posto,
      nome_guerra: p.nome_guerra,
    };
  }
  function exigirPerfil(...perfis) {
    if (!perfis.includes(usuarioAtual().perfil)) {
      throw regra(403, "SEM_PERMISSAO", "Seu perfil não tem acesso a esta função.");
    }
  }
  const OPERACIONAIS = ["ADMINISTRADOR", "ESTOQUISTA", "EQUIPAMENTISTA"];
  const GESTAO = ["ADMINISTRADOR", "ESTOQUISTA"];

  function registrar(mov) {
    const m = {
      id: db.proximo.mov++,
      ocorrida_em: iso(agora()),
      executado_por: db.sessao,
      unidade_id: null,
      pessoa_id: null,
      variacao: null,
      status_anterior: null,
      status_novo: null,
      estado_retirada: null,
      estado_devolucao: null,
      observacao: null,
      finalidade: null,
      documento_ref: null,
      prazo_devolucao: null,
      operacao: null,
      ...mov,
    };
    db.movimentacoes.push(m);
    indexar(m);
    return m;
  }
  function auditar(acao, entidade, entidadeId, detalhe = {}) {
    db.auditoria.unshift({
      id: db.proximo.outro++,
      ocorrida_em: iso(agora()),
      acao,
      entidade,
      entidade_id: entidadeId,
      detalhe,
      executor_posto: usuarioAtual().posto,
      executor_guerra: usuarioAtual().nome_guerra,
    });
  }
  function exigirPessoaNaUnidade(pid) {
    const p = pessoa(pid);
    if (!p) throw regra(404, "NAO_ENCONTRADO", `Pessoa ${pid} não existe.`);
    if (!naUnidade(p)) {
      throw regra(409, "PESSOA_FORA_DA_UNIDADE", `${rotulo(p)} não está na unidade hoje.`);
    }
    return p;
  }

  function retirar(corpo) {
    exigirPerfil(...OPERACIONAIS);
    const pid = id(corpo.pessoa_id, "pessoa_id");
    if (!Array.isArray(corpo.itens) || corpo.itens.length === 0 || corpo.itens.length > 20) {
      throw invalido("itens", "Informe de 1 a 20 materiais.");
    }
    const estado = umDe(corpo.estado ?? "BOM", "estado", ["BOM", "REGULAR"]);
    const finalidade = texto(corpo.finalidade, "finalidade", 120);
    const observacao = texto(corpo.observacao, "observacao", 500);
    if (estado === "REGULAR" && observacao === null) {
      throw regra(
        422,
        "PARAMETRO_INVALIDO",
        "Material em estado regular exige observação descrevendo as marcas de uso.",
      );
    }
    exigirPessoaNaUnidade(pid);
    const vistos = new Set();
    // Primeiro confere tudo; só depois grava (tudo ou nada, como a transação da API).
    const plano = corpo.itens.map((item, i) => {
      const mid = id(item?.material_id, `itens[${i}].material_id`);
      if (vistos.has(mid))
        throw invalido("itens", "O mesmo material aparece duas vezes: junte as quantidades.");
      vistos.add(mid);
      const mat = db.materialPorId.get(mid);
      if (!mat) throw regra(404, "NAO_ENCONTRADO", `Material ${mid} não existe.`);
      if (Array.isArray(item.unidades) && item.unidades.length > 0) {
        if (mat.controle !== "SERIAL")
          throw regra(
            409,
            "OPERACAO_INCOMPATIVEL",
            "Material de consumo não tem unidades com BMP.",
          );
        const us = item.unidades.map((uid) => db.unidadePorId.get(uid));
        if (us.some((u) => !u || u.material_tipo_id !== mid)) {
          throw regra(
            422,
            "PARAMETRO_INVALIDO",
            `Alguma unidade informada não existe ou não é de ${mat.nome}.`,
          );
        }
        const ocupada = us.find((u) => u.status !== "DISPONIVEL");
        if (ocupada)
          throw regra(
            409,
            "OPERACAO_INCOMPATIVEL",
            `A unidade BMP ${ocupada.bmp} não está disponível.`,
          );
        return { mat, unidades: us };
      }
      const q = inteiro(item.quantidade, `itens[${i}].quantidade`, 1, 500);
      if (mat.controle === "CONSUMO") {
        if ((mat.saldo ?? 0) < q) {
          throw regra(
            409,
            "ESTOQUE_INSUFICIENTE",
            `Estoque insuficiente do material ${mat.nome}: saldo ${mat.saldo ?? 0}, pedido ${q}.`,
          );
        }
        return { mat, quantidade: q };
      }
      if (mat.prazo_devolucao_horas == null)
        throw regra(409, "OPERACAO_INCOMPATIVEL", `${mat.nome} não é cautelável.`);
      const livres = db.unidades
        .filter((u) => u.material_tipo_id === mid && u.status === "DISPONIVEL")
        .sort((a, b) => a.id - b.id);
      if (livres.length < q) {
        throw regra(
          409,
          "ESTOQUE_INSUFICIENTE",
          `Estoque insuficiente de ${mat.nome}: ${livres.length} disponível(is), pedido ${q}.`,
        );
      }
      return { mat, unidades: livres.slice(0, q) };
    });
    const operacao = uuid();
    const quando = iso(agora());
    const itens = plano.map(({ mat, unidades, quantidade }) => {
      if (quantidade !== undefined) {
        mat.saldo -= quantidade;
        registrar({
          ocorrida_em: quando,
          tipo: "RETIRADA",
          material_tipo_id: mat.id,
          pessoa_id: pid,
          variacao: -quantidade,
          operacao,
          finalidade,
          observacao,
        });
        return {
          material_tipo_id: mat.id,
          material: mat.nome,
          controle: mat.controle,
          quantidade,
          prazo: null,
          ocorrida_em: quando,
          bmps: [],
        };
      }
      const prazo = iso(Date.now() + mat.prazo_devolucao_horas * 3600000);
      for (const u of unidades) {
        u.status = "CAUTELADA";
        u.detentor_id = pid;
        registrar({
          ocorrida_em: quando,
          tipo: "RETIRADA",
          material_tipo_id: mat.id,
          unidade_id: u.id,
          pessoa_id: pid,
          variacao: -1,
          status_anterior: "DISPONIVEL",
          status_novo: "CAUTELADA",
          estado_retirada: estado,
          operacao,
          finalidade,
          observacao,
          prazo_devolucao: prazo,
        });
      }
      return {
        material_tipo_id: mat.id,
        material: mat.nome,
        controle: mat.controle,
        quantidade: unidades.length,
        prazo,
        ocorrida_em: quando,
        bmps: unidades.map((u) => u.bmp).sort(),
      };
    });
    itens.sort((a, b) => a.material.localeCompare(b.material));
    return [201, { operacao, itens }];
  }

  function devolver(corpo) {
    exigirPerfil(...OPERACIONAIS);
    const pid = id(corpo.pessoa_id, "pessoa_id");
    if (
      !Array.isArray(corpo.unidades) ||
      corpo.unidades.length === 0 ||
      corpo.unidades.length > 500
    ) {
      throw invalido("unidades", "Informe de 1 a 500 unidades.");
    }
    const estado = umDe(corpo.estado ?? "BOM", "estado", ["BOM", "AVARIADO", "INSERVIVEL"]);
    const observacao = texto(corpo.observacao, "observacao", 500);
    if (estado !== "BOM" && observacao === null) {
      throw regra(
        422,
        "PARAMETRO_INVALIDO",
        `Devolução com material ${estado} exige observação descrevendo o problema.`,
      );
    }
    const us = corpo.unidades.map((uid) => db.unidadePorId.get(uid));
    for (const [i, u] of us.entries()) {
      if (!u) throw regra(404, "NAO_ENCONTRADO", `Unidade ${corpo.unidades[i]} não existe.`);
      if (u.status !== "CAUTELADA")
        throw regra(
          409,
          "OPERACAO_INCOMPATIVEL",
          `A unidade BMP ${u.bmp} não está em posse e não pode ser devolvida.`,
        );
      if (u.detentor_id !== pid)
        throw regra(409, "NAO_E_O_DETENTOR", `A unidade BMP ${u.bmp} está com outro militar.`);
    }
    const novo = { BOM: "DISPONIVEL", AVARIADO: "EM_MANUTENCAO", INSERVIVEL: "BAIXA_PENDENTE" }[
      estado
    ];
    const operacao = uuid();
    const quando = iso(agora());
    for (const u of us) {
      u.status = novo;
      u.detentor_id = null;
      registrar({
        ocorrida_em: quando,
        tipo: "DEVOLUCAO",
        material_tipo_id: u.material_tipo_id,
        unidade_id: u.id,
        pessoa_id: pid,
        variacao: 1,
        status_anterior: "CAUTELADA",
        status_novo: novo,
        estado_devolucao: estado,
        observacao,
        operacao,
      });
    }
    return [201, { operacao, quantidade: us.length }];
  }

  function entrada(mid, corpo) {
    exigirPerfil(...GESTAO);
    const mat = db.materialPorId.get(mid);
    if (!mat) throw regra(404, "NAO_ENCONTRADO", "Material não encontrado.");
    const q = inteiro(corpo.quantidade, "quantidade", 1, 100000);
    const documento = texto(corpo.documento, "documento", 40);
    const observacao = texto(corpo.observacao, "observacao", 500);
    if (mat.controle === "CONSUMO") {
      mat.saldo = (mat.saldo ?? 0) + q;
      registrar({
        tipo: "ENTRADA",
        material_tipo_id: mid,
        variacao: q,
        documento_ref: documento,
        observacao,
      });
      return [201, { quantidade: q }];
    }
    if (q > 500) throw invalido("quantidade", "No máximo 500 unidades por entrada.");
    const local = id(corpo.local_id, "local_id");
    if (!db.localPorId.has(local)) throw regra(404, "NAO_ENCONTRADO", "Local não encontrado.");
    const estado = umDe(corpo.estado ?? "BOM", "estado", ["BOM", "AVARIADO", "INSERVIVEL"]);
    const status = { BOM: "DISPONIVEL", AVARIADO: "EM_MANUTENCAO", INSERVIVEL: "BAIXA_PENDENTE" }[
      estado
    ];
    let bmp = Math.max(...db.unidades.map((u) => Number(u.bmp) || 0));
    const bmps = [];
    for (let i = 0; i < q; i++) {
      bmp += 1;
      const u = {
        id: db.proximo.unidade++,
        material_tipo_id: mid,
        bmp: String(bmp),
        numero_serie: null,
        status,
        local_id: local,
        detentor_id: null,
      };
      db.unidades.push(u);
      db.unidadePorId.set(u.id, u);
      registrar({
        tipo: "ENTRADA",
        material_tipo_id: mid,
        unidade_id: u.id,
        variacao: 1,
        status_novo: status,
        documento_ref: documento,
        observacao,
      });
      bmps.push(u.bmp);
    }
    return [201, { quantidade: q, bmps }];
  }

  function ajuste(mid, corpo) {
    exigirPerfil(...GESTAO);
    const mat = db.materialPorId.get(mid);
    if (!mat) throw regra(404, "NAO_ENCONTRADO", "Material não encontrado.");
    if (mat.controle !== "CONSUMO")
      throw regra(409, "OPERACAO_INCOMPATIVEL", `Material ${mat.nome} não é de consumo.`);
    const contada = inteiro(corpo.quantidade_contada, "quantidade_contada", 0, 10000000);
    const justificativa = texto(corpo.justificativa, "justificativa", 500);
    if (justificativa === null) throw invalido("justificativa", "Explique o motivo do ajuste.");
    const diferenca = contada - (mat.saldo ?? 0);
    if (diferenca === 0) return [201, { ajustado: false }];
    mat.saldo = contada;
    registrar({
      tipo: "AJUSTE",
      material_tipo_id: mid,
      variacao: diferenca,
      observacao: justificativa,
    });
    return [201, { ajustado: true }];
  }

  const TRANSICOES = new Set([
    "DISPONIVEL>EM_MANUTENCAO",
    "DISPONIVEL>NAO_LOCALIZADA",
    "DISPONIVEL>BAIXA_PENDENTE",
    "CAUTELADA>NAO_LOCALIZADA",
    "EM_MANUTENCAO>DISPONIVEL",
    "EM_MANUTENCAO>BAIXA_PENDENTE",
    "NAO_LOCALIZADA>DISPONIVEL",
    "NAO_LOCALIZADA>BAIXA_PENDENTE",
    "BAIXA_PENDENTE>BAIXADA",
    "BAIXA_PENDENTE>DISPONIVEL",
    "AGUARDANDO_TOMBAMENTO>DISPONIVEL",
  ]);
  function situacao(uid, corpo) {
    exigirPerfil(...GESTAO);
    const u = db.unidadePorId.get(uid);
    if (!u) throw regra(404, "NAO_ENCONTRADO", `Unidade ${uid} não existe.`);
    const status = umDe(corpo.status, "status", [
      "DISPONIVEL",
      "EM_MANUTENCAO",
      "NAO_LOCALIZADA",
      "BAIXA_PENDENTE",
      "BAIXADA",
    ]);
    const justificativa = texto(corpo.justificativa, "justificativa", 500);
    if (justificativa === null) throw invalido("justificativa", "Explique o motivo da mudança.");
    if (!TRANSICOES.has(`${u.status}>${status}`)) {
      throw regra(
        409,
        "TRANSICAO_PROIBIDA",
        `Transição de ${u.status} para ${status} não é permitida.`,
      );
    }
    const bmp = texto(corpo.bmp, "bmp", 7);
    if ((u.status === "AGUARDANDO_TOMBAMENTO") !== (bmp !== null)) {
      throw regra(
        422,
        "PARAMETRO_INVALIDO",
        "BMP só é informado no tombamento (e é obrigatório nele).",
      );
    }
    const antes = u.status;
    const detentor = u.detentor_id;
    u.status = status;
    u.detentor_id = null;
    if (bmp) u.bmp = bmp;
    registrar({
      tipo: "MUDANCA_STATUS",
      material_tipo_id: u.material_tipo_id,
      unidade_id: u.id,
      pessoa_id: detentor,
      status_anterior: antes,
      status_novo: status,
      observacao: justificativa,
      documento_ref: bmp ? `BMP ${bmp}` : null,
    });
    return [201, { status }];
  }

  // Cadastros (administrador): só o essencial das regras do banco, com auditoria.
  function duplicado(lista, nome, exceto) {
    if (lista.some((x) => x.id !== exceto && semAcento(x.nome) === semAcento(nome))) {
      throw regra(409, "DUPLICADO", `Já existe "${nome}".`);
    }
  }
  function cadastrarCategoria(corpo) {
    const nome = obrigatorio(corpo.nome, "nome", 120);
    duplicado(db.categorias, nome);
    const c = { id: db.proximo.outro++, nome };
    db.categorias.push(c);
    db.categoriaPorId.set(c.id, c);
    auditar("CADASTRAR", "CATEGORIA", c.id, { nome });
    return [201, { id: c.id }];
  }
  function renomear(lista, mapa, entidade, cid, corpo) {
    const x = mapa.get(cid);
    if (!x) throw regra(404, "NAO_ENCONTRADO", "Registro não encontrado.");
    const nome = obrigatorio(corpo.nome, "nome", 120);
    duplicado(
      entidade === "SUBCATEGORIA" ? lista.filter((s) => s.categoria_id === x.categoria_id) : lista,
      nome,
      cid,
    );
    auditar("RENOMEAR", entidade, cid, { nome: { antes: x.nome, depois: nome } });
    x.nome = nome;
    return [204, null];
  }
  function cadastrarSubcategoria(corpo) {
    const cat = id(corpo.categoria_id, "categoria_id");
    if (!db.categoriaPorId.has(cat))
      throw regra(404, "NAO_ENCONTRADO", "Categoria não encontrada.");
    const nome = obrigatorio(corpo.nome, "nome", 120);
    duplicado(
      db.subcategorias.filter((s) => s.categoria_id === cat),
      nome,
    );
    const s = { id: db.proximo.outro++, categoria_id: cat, nome };
    db.subcategorias.push(s);
    db.subPorId.set(s.id, s);
    auditar("CADASTRAR", "SUBCATEGORIA", s.id, { nome });
    return [201, { id: s.id }];
  }
  function cadastrarMaterial(c) {
    const nome = obrigatorio(c.nome, "nome", 120);
    duplicado(db.materiais, nome);
    const sub = id(c.subcategoria_id, "subcategoria_id");
    if (!db.subPorId.has(sub)) throw regra(404, "NAO_ENCONTRADO", "Subcategoria não encontrada.");
    const controle = umDe(c.controle, "controle", ["SERIAL", "CONSUMO"]);
    const n = db.materiais.filter((m) => m.codigo.startsWith("DEM-")).length + 1;
    const m = {
      id: db.proximo.outro++,
      codigo: `DEM-${String(n).padStart(4, "0")}`,
      nome,
      descricao: texto(c.descricao, "descricao", 500),
      controle,
      unidade_medida: c.unidade_medida ?? "UN",
      prazo_devolucao_horas:
        controle === "SERIAL"
          ? inteiroOpcional(c.prazo_devolucao_horas, "prazo_devolucao_horas", 1, 8760)
          : null,
      custo_unitario: Number(c.custo_unitario ?? 0),
      ativo: true,
      subcategoria_id: sub,
      estoque_minimo:
        controle === "SERIAL"
          ? (inteiroOpcional(c.estoque_minimo, "estoque_minimo", 0, 1000000) ?? 0)
          : null,
      saldo: controle === "CONSUMO" ? 0 : null,
      minimo_consumo:
        controle === "CONSUMO"
          ? (inteiroOpcional(c.estoque_minimo, "estoque_minimo", 0, 1000000) ?? 0)
          : null,
      estoque_maximo:
        controle === "CONSUMO"
          ? inteiroOpcional(c.estoque_maximo, "estoque_maximo", 1, 1000000)
          : null,
      local_id: c.local_id ?? null,
    };
    db.materiais.push(m);
    db.materialPorId.set(m.id, m);
    auditar("CADASTRAR", "MATERIAL", m.id, { nome, controle });
    return [201, { id: m.id }];
  }
  function atualizarMaterial(mid, c) {
    const m = db.materialPorId.get(mid);
    if (!m) throw regra(404, "NAO_ENCONTRADO", "Material não encontrado.");
    const novo = {
      nome: obrigatorio(c.nome, "nome", 120),
      subcategoria_id: id(c.subcategoria_id, "subcategoria_id"),
      prazo_devolucao_horas: inteiroOpcional(
        c.prazo_devolucao_horas,
        "prazo_devolucao_horas",
        1,
        8760,
      ),
      custo_unitario: Number(c.custo_unitario ?? 0),
      descricao: texto(c.descricao, "descricao", 500),
      ativo: c.ativo !== false,
    };
    duplicado(db.materiais, novo.nome, mid);
    const minimo = inteiroOpcional(c.estoque_minimo, "estoque_minimo", 0, 1000000);
    const detalhe = {};
    for (const [k, v] of Object.entries(novo)) {
      if (m[k] !== v) detalhe[k] = { antes: m[k], depois: v };
      m[k] = v;
    }
    const campoMinimo = m.controle === "SERIAL" ? "estoque_minimo" : "minimo_consumo";
    if (minimo !== null && m[campoMinimo] !== minimo) {
      detalhe.estoque_minimo = { antes: m[campoMinimo], depois: minimo };
      m[campoMinimo] = minimo;
    }
    if (Object.keys(detalhe).length) auditar("ATUALIZAR", "MATERIAL", mid, detalhe);
    return [204, null];
  }
  function cadastrarPessoa(c) {
    const matricula = obrigatorio(c.matricula, "matricula", 7);
    if (!/^\d{7}$/.test(matricula))
      throw regra(422, "PARAMETRO_INVALIDO", "A matrícula tem 7 dígitos.");
    if (db.pessoas.some((p) => p.matricula === matricula))
      throw regra(409, "DUPLICADO", "Já existe um militar com essa matrícula.");
    const guerra = obrigatorio(c.nome_guerra, "nome_guerra", 30);
    if (
      db.pessoas.some((p) => p.data_saida == null && semAcento(p.nome_guerra) === semAcento(guerra))
    ) {
      throw regra(409, "DUPLICADO", "Já existe um militar na unidade com esse nome de guerra.");
    }
    if (!db.postoPorSigla.has(c.posto)) throw invalido("posto", "Posto/graduação inválido.");
    const setor = id(c.setor_id, "setor_id");
    const p = {
      id: db.proximo.outro++,
      matricula,
      nome: obrigatorio(c.nome, "nome", 120),
      nome_guerra: guerra.toUpperCase(),
      posto: c.posto,
      setor_id: setor,
      data_entrada: c.data_entrada || hojeLocal(),
      data_saida: null,
    };
    db.pessoas.push(p);
    db.pessoaPorId.set(p.id, p);
    auditar("CADASTRAR", "PESSOA", p.id, { matricula });
    return [201, { id: p.id }];
  }
  function atualizarPessoa(pid, c) {
    const p = pessoa(pid);
    if (!p) throw regra(404, "NAO_ENCONTRADO", "Militar não encontrado.");
    if (!db.postoPorSigla.has(c.posto)) throw invalido("posto", "Posto/graduação inválido.");
    const novo = {
      nome: obrigatorio(c.nome, "nome", 120),
      nome_guerra: obrigatorio(c.nome_guerra, "nome_guerra", 30).toUpperCase(),
      posto: c.posto,
      setor_id: id(c.setor_id, "setor_id"),
    };
    const detalhe = {};
    for (const [k, v] of Object.entries(novo)) {
      if (p[k] !== v) detalhe[k] = { antes: p[k], depois: v };
      p[k] = v;
    }
    if (Object.keys(detalhe).length) auditar("ATUALIZAR", "PESSOA", pid, detalhe);
    return [204, null];
  }
  function saidaPessoa(pid, c) {
    const p = pessoa(pid);
    if (!p) throw regra(404, "NAO_ENCONTRADO", "Militar não encontrado.");
    const data = obrigatorio(c.data_saida, "data_saida", 10);
    const posse = emPosseDe(pid);
    if (posse > 0)
      throw regra(
        409,
        "OPERACAO_INCOMPATIVEL",
        `${rotulo(p)} ainda tem ${posse} unidade(s) em posse: receba a devolução antes da saída.`,
      );
    p.data_saida = data;
    for (const u of db.usuarios) if (u.pessoa_id === pid) u.ativo = false;
    auditar("REGISTRAR_SAIDA", "PESSOA", pid, { data_saida: data });
    return [204, null];
  }
  function cadastrarUsuario(c) {
    const pid = id(c.pessoa_id, "pessoa_id");
    if (db.usuarios.some((u) => u.pessoa_id === pid))
      throw regra(409, "DUPLICADO", "Esse militar já tem usuário.");
    const login = obrigatorio(c.login, "login", 32).toLowerCase();
    if (db.usuarios.some((u) => u.login === login))
      throw regra(409, "DUPLICADO", "Esse login já existe.");
    const perfil = umDe(c.perfil, "perfil", [
      "ADMINISTRADOR",
      "ESTOQUISTA",
      "EQUIPAMENTISTA",
      "CONSULTA",
    ]);
    if (typeof c.senha !== "string" || c.senha.length < 10 || c.senha.length > 128) {
      throw invalido("senha", "A senha deve ter de 10 a 128 caracteres.");
    }
    const u = { id: db.proximo.outro++, login, perfil, ativo: true, pessoa_id: pid };
    db.usuarios.push(u);
    db.usuarioPorId.set(u.id, u);
    auditar("CADASTRAR", "USUARIO", u.id, { login, perfil });
    auditar("DEFINIR_SENHA", "USUARIO", u.id);
    return [201, { id: u.id }];
  }
  function alterarUsuario(uid, c) {
    const u = db.usuarioPorId.get(uid);
    if (!u) throw regra(404, "NAO_ENCONTRADO", "Usuário não encontrado.");
    const perfil = umDe(c.perfil, "perfil", [
      "ADMINISTRADOR",
      "ESTOQUISTA",
      "EQUIPAMENTISTA",
      "CONSULTA",
    ]);
    const ativo = c.ativo !== false;
    if (uid === db.sessao && (perfil !== "ADMINISTRADOR" || !ativo)) {
      throw regra(
        409,
        "OPERACAO_INCOMPATIVEL",
        "Você não pode tirar o seu próprio acesso de administrador.",
      );
    }
    const adminsRestantes = db.usuarios.filter(
      (x) => x.ativo && x.perfil === "ADMINISTRADOR" && x.id !== uid,
    ).length;
    if (adminsRestantes === 0 && (perfil !== "ADMINISTRADOR" || !ativo)) {
      throw regra(
        409,
        "OPERACAO_INCOMPATIVEL",
        "O sistema precisa de pelo menos um administrador ativo.",
      );
    }
    const detalhe = {};
    if (u.perfil !== perfil) detalhe.perfil = { antes: u.perfil, depois: perfil };
    if (u.ativo !== ativo) detalhe.ativo = { antes: u.ativo, depois: ativo };
    Object.assign(u, { perfil, ativo });
    if (Object.keys(detalhe).length) auditar("ALTERAR", "USUARIO", uid, detalhe);
    return [204, null];
  }

  // ------------------------------------------------------------------ roteador
  function query(url, nome) {
    const v = url.searchParams.get(nome);
    return v === null || v === "" ? null : v;
  }
  const idQuery = (url, nome) => {
    const v = query(url, nome);
    if (v === null) return null;
    if (!/^[1-9][0-9]{0,9}$/.test(v)) throw invalido(nome, `${nome} inválido.`);
    return Number(v);
  };
  function termo(url) {
    const t = (url.searchParams.get("busca") ?? "").trim();
    if (t.length < 2) throw invalido("busca", "Digite pelo menos 2 caracteres.");
    return t;
  }

  function rotear(metodo, caminho, url, corpo) {
    const [, recurso, rid, sub] = caminho.split("/");
    const n = rid !== undefined ? Number(rid) : null;

    // Sessão (sem login obrigatório)
    if (caminho === "/sessao") {
      if (metodo === "GET") return [200, { usuario: usuarioAtual() }];
      if (metodo === "DELETE") {
        db.sessao = null;
        return [204, null];
      }
      if (metodo === "POST") {
        const login = String(corpo?.login ?? "")
          .trim()
          .toLowerCase();
        if (!corpo?.senha) throw invalido("senha", "Informe a senha.");
        const u = db.usuarios.find((x) => x.login === login && x.ativo);
        if (!u)
          throw regra(
            401,
            "CREDENCIAIS_INVALIDAS",
            "Login ou senha inválidos. Na demo: rafaela.01, enzo.04 ou heitor.09, com qualquer senha.",
          );
        db.sessao = u.id;
        return [200, { usuario: usuarioAtual() }];
      }
    }
    if (!usuarioAtual()) throw regra(401, "SEM_SESSAO", "Sessão expirada. Entre de novo.");
    const admin = usuarioAtual().perfil === "ADMINISTRADOR";
    const soAdmin = () => exigirPerfil("ADMINISTRADOR");

    if (metodo === "GET") {
      switch (recurso) {
        case "referencias":
          return [
            200,
            {
              postos: db.postos.map(({ sigla, nome, circulo }) => ({ sigla, nome, circulo })),
              setores: db.setores,
              locais: db.locais,
              categorias: [...db.categorias]
                .sort((a, b) => a.nome.localeCompare(b.nome))
                .map((c) => ({
                  id: c.id,
                  nome: c.nome,
                  subcategorias: db.subcategorias
                    .filter((s) => s.categoria_id === c.id)
                    .sort((a, b) => a.nome.localeCompare(b.nome))
                    .map(({ id: sid, nome }) => ({ id: sid, nome })),
                })),
            },
          ];
        case "resumo": {
          const hoje = inicioDoDia(hojeLocal());
          const atendimentos = (tipo) =>
            new Set(
              db.movimentacoes
                .filter((m) => m.tipo === tipo && ms(m.ocorrida_em) >= hoje)
                .map((m) => m.operacao ?? m.id),
            ).size;
          const posse = db.unidades.filter((u) => u.status === "CAUTELADA");
          return [
            200,
            {
              contadores: {
                em_posse: posse.length,
                militares_com_material: new Set(posse.map((u) => u.detentor_id)).size,
                vencidas: posseAgrupada({ soVencidas: true }).length,
                abaixo_do_minimo: db.materiais.filter(
                  (m) => m.ativo && estoque(m).situacao !== "NORMAL",
                ).length,
                em_manutencao: db.unidades.filter((u) => u.status === "EM_MANUTENCAO").length,
                retiradas_hoje: atendimentos("RETIRADA"),
                devolucoes_hoje: atendimentos("DEVOLUCAO"),
              },
              vencidas: posseAgrupada({ soVencidas: true, limite: 6 }),
              ultimas: historico({ limite: 8 }),
            },
          ];
        }
        case "pessoas": {
          const t = termo(url);
          const pessoas = db.pessoas
            .filter(
              (p) =>
                naUnidade(p) &&
                (p.matricula.startsWith(t) ||
                  contem(`${p.posto} ${p.nome_guerra}`, t) ||
                  contem(p.nome, t)),
            )
            .sort((a, b) => a.nome_guerra.toLowerCase().localeCompare(b.nome_guerra.toLowerCase()))
            .slice(0, 20)
            .map((p) => ({
              id: p.id,
              posto: p.posto,
              nome_guerra: p.nome_guerra,
              nome: p.nome,
              matricula: p.matricula,
              setor: db.setorPorId.get(p.setor_id)?.sigla,
              em_posse: emPosseDe(p.id),
            }));
          return [200, { pessoas }];
        }
        case "militares": {
          const ordem = (p) => db.postoPorSigla.get(p.posto)?.ordem ?? 0;
          const militares = [...db.pessoas]
            .sort(
              (a, b) =>
                (a.data_saida != null) - (b.data_saida != null) ||
                ordem(b) - ordem(a) ||
                a.nome_guerra.toLowerCase().localeCompare(b.nome_guerra.toLowerCase()),
            )
            .map((p) => {
              const u = db.usuarios.find((x) => x.pessoa_id === p.id);
              return {
                id: p.id,
                posto: p.posto,
                posto_ordem: ordem(p),
                nome_guerra: p.nome_guerra,
                nome: p.nome,
                matricula: p.matricula,
                setor_id: p.setor_id,
                setor: db.setorPorId.get(p.setor_id)?.sigla,
                data_entrada: p.data_entrada,
                data_saida: p.data_saida,
                na_unidade: p.data_saida == null || p.data_saida > hojeLocal(),
                usuario_id: admin ? (u?.id ?? null) : null,
                login: admin ? (u?.login ?? null) : null,
                perfil: admin ? (u?.perfil ?? null) : null,
                usuario_ativo: admin ? (u?.ativo ?? null) : null,
                em_posse: emPosseDe(p.id),
              };
            });
          return [200, { militares }];
        }
        case "estoque": {
          if (n === null) {
            const materiais = db.materiais
              .map(estoque)
              .sort(
                (a, b) => a.categoria.localeCompare(b.categoria) || a.nome.localeCompare(b.nome),
              );
            return [200, { materiais }];
          }
          const m = db.materialPorId.get(n);
          if (!m) throw regra(404, "NAO_ENCONTRADO", "Material não encontrado.");
          const ORDEM = [
            "DISPONIVEL",
            "CAUTELADA",
            "EM_MANUTENCAO",
            "NAO_LOCALIZADA",
            "BAIXA_PENDENTE",
            "AGUARDANDO_TOMBAMENTO",
            "BAIXADA",
          ];
          const unidades = db.unidades
            .filter((u) => u.material_tipo_id === n)
            .sort(
              (a, b) =>
                ORDEM.indexOf(a.status) - ORDEM.indexOf(b.status) ||
                String(a.bmp ?? "￿").localeCompare(String(b.bmp ?? "￿")),
            )
            .map((u) => {
              const p = pessoa(u.detentor_id);
              return {
                id: u.id,
                bmp: u.bmp,
                numero_serie: u.numero_serie,
                status: u.status,
                local: db.localPorId.get(u.local_id)?.nome,
                pessoa_id: p?.id ?? null,
                posto: p?.posto ?? null,
                nome_guerra: p?.nome_guerra ?? null,
              };
            });
          const material = {
            ...estoque(m),
            estoque_maximo: m.estoque_maximo ?? null,
            local_id: m.local_id ?? null,
            local: db.localPorId.get(m.local_id)?.nome ?? null,
          };
          return [200, { material, unidades, movimentos: historico({ material: n, limite: 10 }) }];
        }
        case "unidades": {
          const t = termo(url);
          const unidades = db.unidades
            .filter((u) => {
              const m = db.materialPorId.get(u.material_tipo_id);
              return (
                m.prazo_devolucao_horas != null &&
                (u.bmp === t ||
                  semAcento(u.numero_serie).startsWith(semAcento(t)) ||
                  contem(m.nome, t))
              );
            })
            .map((u) => {
              const m = db.materialPorId.get(u.material_tipo_id);
              const p = pessoa(u.detentor_id);
              return {
                id: u.id,
                bmp: u.bmp,
                numero_serie: u.numero_serie,
                status: u.status,
                material_tipo_id: m.id,
                codigo: m.codigo,
                material: m.nome,
                prazo_devolucao_horas: m.prazo_devolucao_horas,
                detentor_posto: p?.posto ?? null,
                detentor_guerra: p?.nome_guerra ?? null,
              };
            })
            .sort(
              (a, b) =>
                (b.status === "DISPONIVEL") - (a.status === "DISPONIVEL") ||
                a.material.localeCompare(b.material) ||
                String(a.bmp ?? "￿").localeCompare(String(b.bmp ?? "￿")),
            )
            .slice(0, 20);
          return [200, { unidades }];
        }
        case "posse":
          return [200, { grupos: posseAgrupada({ pessoaId: idQuery(url, "pessoa_id") }) }];
        case "movimentacoes": {
          const tipo = query(url, "tipo");
          if (
            tipo &&
            !["ENTRADA", "RETIRADA", "DEVOLUCAO", "MUDANCA_STATUS", "AJUSTE", "ESTORNO"].includes(
              tipo,
            )
          )
            throw invalido("tipo", "tipo inválido.");
          const antesEm = query(url, "antes_em");
          const antesId = idQuery(url, "antes_id");
          const linhas = historico({
            de: query(url, "de"),
            ate: query(url, "ate"),
            tipo,
            busca: query(url, "busca"),
            material: idQuery(url, "material_id"),
            pessoa: idQuery(url, "pessoa_id"),
            antes: antesEm && antesId ? { em: antesEm, id: antesId } : null,
            limite: 51,
          });
          return [200, { movimentacoes: linhas.slice(0, 50), tem_mais: linhas.length > 50 }];
        }
        case "ciclo": {
          const itens = ciclo(query(url, "operacao"), idQuery(url, "movimentacao"));
          if (itens.length === 0) throw regra(404, "NAO_ENCONTRADO", "Operação não encontrada.");
          return [200, { itens }];
        }
        case "usuarios": {
          soAdmin();
          const ORDEM = ["ADMINISTRADOR", "ESTOQUISTA", "EQUIPAMENTISTA", "CONSULTA"];
          const usuarios = [...db.usuarios]
            .sort(
              (a, b) =>
                b.ativo - a.ativo ||
                ORDEM.indexOf(a.perfil) - ORDEM.indexOf(b.perfil) ||
                a.login.localeCompare(b.login),
            )
            .map((u) => {
              const p = pessoa(u.pessoa_id);
              return {
                id: u.id,
                login: u.login,
                perfil: u.perfil,
                ativo: u.ativo,
                pessoa_id: p.id,
                posto: p.posto,
                nome_guerra: p.nome_guerra,
                nome: p.nome,
                tem_senha: true,
                senha_atualizada_em: null,
                ultima_entrada: u.id === db.sessao ? iso(agora()) : null,
              };
            });
          return [200, { usuarios }];
        }
        case "auditoria":
          soAdmin();
          return [
            200,
            {
              registros: db.auditoria.map((a) => ({
                ...a,
                alvo:
                  {
                    MATERIAL: () => db.materialPorId.get(a.entidade_id)?.nome,
                    CATEGORIA: () => db.categoriaPorId.get(a.entidade_id)?.nome,
                    SUBCATEGORIA: () => db.subPorId.get(a.entidade_id)?.nome,
                    PESSOA: () => rotulo(pessoa(a.entidade_id)),
                    USUARIO: () => db.usuarioPorId.get(a.entidade_id)?.login,
                  }[a.entidade]?.() ?? null,
              })),
            },
          ];
      }
    }

    if (metodo === "POST") {
      if (caminho === "/retiradas") return retirar(corpo);
      if (caminho === "/devolucoes") return devolver(corpo);
      if (caminho === "/sessao/senha") {
        if (typeof corpo.senha_nova !== "string" || corpo.senha_nova.length < 10)
          throw invalido("senha_nova", "A senha deve ter de 10 a 128 caracteres.");
        auditar("TROCAR_SENHA", "USUARIO", db.sessao);
        return [204, null];
      }
      if (recurso === "materiais" && sub === "entradas") return entrada(n, corpo);
      if (recurso === "materiais" && sub === "ajuste") return ajuste(n, corpo);
      if (recurso === "unidades" && sub === "situacao") return situacao(n, corpo);
      soAdmin();
      if (caminho === "/categorias") return cadastrarCategoria(corpo);
      if (caminho === "/subcategorias") return cadastrarSubcategoria(corpo);
      if (caminho === "/materiais") return cadastrarMaterial(corpo);
      if (caminho === "/militares") return cadastrarPessoa(corpo);
      if (recurso === "militares" && sub === "saida") return saidaPessoa(n, corpo);
      if (caminho === "/usuarios") return cadastrarUsuario(corpo);
      if (recurso === "usuarios" && sub === "senha") {
        if (typeof corpo.senha !== "string" || corpo.senha.length < 10)
          throw invalido("senha", "A senha deve ter de 10 a 128 caracteres.");
        auditar("DEFINIR_SENHA", "USUARIO", n);
        return [204, null];
      }
    }
    if (metodo === "PATCH" || metodo === "PUT") {
      soAdmin();
      if (recurso === "categorias")
        return renomear(db.categorias, db.categoriaPorId, "CATEGORIA", n, corpo);
      if (recurso === "subcategorias")
        return renomear(db.subcategorias, db.subPorId, "SUBCATEGORIA", n, corpo);
      if (recurso === "materiais") return atualizarMaterial(n, corpo);
      if (recurso === "militares") return atualizarPessoa(n, corpo);
      if (recurso === "usuarios") return alterarUsuario(n, corpo);
    }
    throw regra(404, "NAO_ENCONTRADO", "Rota não encontrada.");
  }

  // ------------------------------------------------------------------ fetch interceptado
  window.fetch = async (recurso, opcoes = {}) => {
    const url = new URL(typeof recurso === "string" ? recurso : recurso.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) {
      return fetchOriginal(recurso, opcoes);
    }
    await pronto;
    const metodo = (opcoes.method ?? "GET").toUpperCase();
    let corpo = {};
    try {
      corpo = opcoes.body ? JSON.parse(opcoes.body) : {};
    } catch {
      corpo = {};
    }
    // Um pequeno atraso para os estados de carregamento da tela aparecerem como no real.
    await new Promise((r) => setTimeout(r, 120));
    let status;
    let resposta;
    try {
      [status, resposta] = rotear(metodo, url.pathname.slice(4), url, corpo);
    } catch (erro) {
      if (!(erro instanceof Erro)) {
        console.error("[demo]", erro);
        status = 500;
        resposta = { erro: "Erro interno da demo.", codigo: "ERRO_INTERNO" };
      } else {
        status = erro.status;
        resposta = {
          erro: erro.message,
          codigo: erro.codigo,
          ...(erro.campo ? { campo: erro.campo } : {}),
        };
      }
    }
    return new Response(status === 204 ? null : JSON.stringify(resposta), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
})();
