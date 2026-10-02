// Monta a demo estática (sem servidor) do sistema.
//
// Reaproveita a tela de web/ sem alterá-la: copia tudo, injeta demo/demo-api.js (que
// responde às chamadas /api no navegador) antes do app e um aviso de que é uma demo, e
// coloca o retrato dos dados ao lado do script.
//
// Uso:
//   python demo/exportar_dados.py                 (gera demo/dados-demo.json)
//   node demo/build.mjs [pasta-de-destino]        (padrão: demo/dist)

import fs from "node:fs";
import path from "node:path";

const raiz = path.resolve(import.meta.dirname, "..");
const destino = path.resolve(process.argv[2] ?? path.join(raiz, "demo", "dist"));
const REPOSITORIO = "https://github.com/DiegoSantiago1/controle-materiais-cautela";

const dados = path.join(raiz, "demo", "dados-demo.json");
if (!fs.existsSync(dados)) {
  throw new Error("Falta demo/dados-demo.json. Rode: python demo/exportar_dados.py");
}

const aviso = `
    <aside id="aviso-demo" role="note" style="position:fixed;right:16px;bottom:16px;z-index:200;max-width:340px;display:flex;gap:10px;align-items:flex-start;padding:12px 12px 12px 14px;border-radius:12px;background:#0d2c1c;color:#eef6f0;font:13px/1.5 system-ui,'Segoe UI',Arial,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.35)">
      <span><b>Demo com dados fictícios.</b> O que você fizer aqui fica só neste navegador (recarregar volta ao início). Você entra como administradora; para ver outro perfil, saia e entre com <b>enzo.04</b> (equipamentista) ou <b>heitor.09</b> (consulta), com qualquer senha.<br>
      <a href="${REPOSITORIO}" target="_blank" rel="noopener noreferrer" style="color:#9be3b5">Código no GitHub ↗</a> · <a href="${REPOSITORIO}/blob/main/docs/POWERBI.md" target="_blank" rel="noopener noreferrer" style="color:#9be3b5">Relatórios no Power BI ↗</a></span>
      <button type="button" aria-label="Fechar aviso" onclick="this.parentElement.remove()" style="all:unset;cursor:pointer;color:#9fbfaa;font-size:18px;line-height:1;padding:0 2px">×</button>
    </aside>`;

fs.rmSync(destino, { recursive: true, force: true });
fs.cpSync(path.join(raiz, "web"), destino, { recursive: true });
fs.mkdirSync(path.join(destino, "demo"), { recursive: true });
fs.copyFileSync(path.join(raiz, "demo", "demo-api.js"), path.join(destino, "demo", "demo-api.js"));
fs.copyFileSync(dados, path.join(destino, "demo", "dados-demo.json"));

const indice = path.join(destino, "index.html");
let html = fs.readFileSync(indice, "utf8");
const app = '<script type="module" src="js/app.js"></script>';
if (!html.includes(app) || !html.includes("</body>")) {
  throw new Error("index.html mudou: não achei o script do app ou o </body>.");
}
html = html
  .replace(app, `<script src="demo/demo-api.js"></script>\n    ${app}`)
  .replace(
    "<title>Controle de Materiais e Cautela</title>",
    "<title>Demo · Controle de Materiais e Cautela</title>",
  )
  .replace("</body>", `${aviso}\n  </body>`);
fs.writeFileSync(indice, html);

const tamanho = fs.statSync(path.join(destino, "demo", "dados-demo.json")).size;
console.log(`demo montada em ${destino} (dados: ${(tamanho / 1024).toFixed(0)} KB)`);
