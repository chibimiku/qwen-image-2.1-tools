// 在 Node 里用 DOM 桩子跑 WebUI 的脚本，专测"只有浏览器里才炸"的逻辑。
// 起不了真浏览器时的替代方案（本沙箱禁止启动 msedge/chrome）。
//   node tools/webui_dom_check.js service/ui/index.html
// 退出码：有 FAIL -> 1
const fs = require('fs');
const vm = require('vm');

const path = process.argv[2];
const html = fs.readFileSync(path, 'utf8');
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
if (!blocks.length) { console.log('FAIL | 没找到 <script> 块'); process.exit(1); }
let code = blocks.map(m => m[1]).join('\n');

// boot() 会去连服务（fetch / sessionState），自检里不需要它 —— 直接让它空转返回。
const before = code.length;
code = code.replace('(async function boot(){', '(async function boot(){ return;');
if (code.length === before) { console.log('FAIL | 没找到 boot() 注入点，自检逻辑需要更新'); process.exit(1); }

/* ---------------- 极简 DOM 桩 ---------------- */
const out = [];
const ok = (name, cond, extra) => out.push((cond ? 'PASS' : 'FAIL') + ' | ' + name +
                                           (extra ? ' | ' + extra : ''));

function makeEl(id) {
  let _value = '';
  const el = {
    id, textContent: '', innerHTML: '', checked: false, disabled: false,
    placeholder: '', title: '', name: '',
    // 真实 <input> 的 value setter 会把任何值强制成字符串 —— 桩子必须一样，
    // 否则会掩盖"把数字塞进输入框"这类问题（params() 里 .trim() 会炸）。
    get value() { return _value; },
    set value(v) { _value = v === null || v === undefined ? '' : String(v); },
    style: new Proxy({}, { get: (t, k) => t[k] ?? '', set: (t, k, v) => (t[k] = v, true) }),
    dataset: {}, children: [], childNodes: [], files: [], options: [], selectedIndex: 0,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
    appendChild(c) { this.children.push(c); return c; }, removeChild() {}, remove() {},
    insertBefore() {}, replaceChildren() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, focus() {}, blur() {}, click() {},
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; },
    scrollIntoView() {}, select() {}, setSelectionRange() {},
    parentElement: null, parentNode: null, firstChild: null, nextSibling: null,
  };
  return el;
}

const els = Object.create(null);
const getEl = id => (els[id] || (els[id] = makeEl(String(id))));

const document = {
  getElementById: getEl,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: tag => makeEl(tag),
  createDocumentFragment: () => makeEl('#frag'),
  addEventListener() {}, removeEventListener() {},
  body: makeEl('body'), documentElement: makeEl('html'),
  cookie: '', readyState: 'complete', title: '',
  execCommand() { return true; },
};

const store = Object.create(null);
const localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
  clear: () => { for (const k of Object.keys(store)) delete store[k]; },
};

const location = { origin: 'http://127.0.0.1:16123', pathname: '/', href: 'http://127.0.0.1:16123/',
                   hash: '', search: '', reload() {}, assign() {}, replace() {} };

const window = {
  innerWidth: 1760, innerHeight: 1000, location, localStorage, document,
  _hist: [], addEventListener() {}, removeEventListener() {}, matchMedia: () => ({ matches: false, addListener() {}, addEventListener() {} }),
  requestAnimationFrame: fn => setTimeout(fn, 0),
};

const sandbox = {
  window, document, localStorage, location,
  navigator: { userAgent: 'node', clipboard: { writeText: async () => {} } },
  fetch: async () => ({ ok: false, status: 503, json: async () => ({}), text: async () => '' }),
  console, setTimeout, clearTimeout, setInterval, clearInterval,
  performance: { now: () => Date.now() },
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  FormData: class { append() {} get() { return null; } getList() { return []; } },
  File: class { constructor(n) { this.name = n; } },
  Blob: class {}, Image: class {}, alert() {}, confirm: () => true, prompt: () => null,
  btoa: s => Buffer.from(s, 'binary').toString('base64'),
  atob: s => Buffer.from(s, 'base64').toString('binary'),
  requestAnimationFrame: fn => setTimeout(fn, 0),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
try {
  vm.runInContext(code, sandbox, { filename: 'ui.js' });
} catch (e) {
  console.log('FAIL | 注入页面脚本就抛异常 | ' + e.message);
  process.exit(1);
}

/* ---------------- 断言 ---------------- */
const g = n => sandbox[n];
const $ = getEl;

if (typeof g('params') !== 'function') {
  console.log('FAIL | 拿不到 params()（页面脚本结构变了，自检需要更新）');
  process.exit(1);
}

// 1) seed：留空 / 负数 = 不指定（服务端自己掷）
for (const [raw, want, note] of [['', 'undefined', '留空'],
                                 ['-5', 'undefined', '负数'],
                                 ['-1', 'undefined', '负数'],
                                 ['0', '0', 'seed 0 是合法种子'],
                                 ['42', '42', '正常种子'],
                                 ['  7  ', '7', '带空格']]) {
  $('seed').value = raw;
  const got = g('params')().seed;
  ok(`seed="${raw}"（${note}）-> params().seed = ${want}`,
     (got === undefined ? 'undefined' : String(got)) === want,
     '实际 ' + (got === undefined ? 'undefined' : JSON.stringify(got)));
}

// 2) 点历史缩略图才把 seed 填回输入框
$('seed').value = '';
g('pushHist')({ b64_json: '', width: 768, height: 1024, seed: 123456 }, 4.2);
ok('历史里记下了这张图的 seed',
   Array.isArray(sandbox.window._hist) && sandbox.window._hist[0] && sandbox.window._hist[0].seed === 123456,
   'hist[0]=' + JSON.stringify(sandbox.window._hist && sandbox.window._hist[0] && sandbox.window._hist[0].seed));
g('showHist')(0);
ok('showHist(0) 把该图 seed 填回输入框', String($('seed').value) === '123456',
   '输入框 = ' + JSON.stringify($('seed').value));
ok('showHist 之后 params() 会用这个 seed 复现', g('params')().seed === 123456,
   'params().seed=' + g('params')().seed);
$('seed').value = '';
ok('清空输入框又回到随机', g('params')().seed === undefined);

// 3) 历史上限与结构
for (let i = 0; i < 20; i++) g('pushHist')({ b64_json: '', width: 8, height: 8, seed: i }, 0.1);
ok('历史只保留最近 12 条', sandbox.window._hist.length === 12, '长度 ' + sandbox.window._hist.length);

console.log(out.join('\n'));
const fails = out.filter(l => l.startsWith('FAIL')).length;
console.log(`--- DOM 自检：${out.length - fails} 通过 / ${fails} 失败 ---`);
process.exit(fails ? 1 : 0);
