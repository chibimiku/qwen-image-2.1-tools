// 用真实服务端数据跑 index.html 里的尺寸逻辑，复现"选 2:3 还发原尺寸"的问题。
// 用法：node tools/webui_fit_check.js <baseUrl> <apiKey>
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const vm = require('vm');

const BASE = process.argv[2] || 'http://127.0.0.1:16006';
const KEY = process.argv[3] || '';

const html = fs.readFileSync(path.join(__dirname, '..', 'service', 'ui', 'index.html'), 'utf8');
const code = /<script[^>]*>([\s\S]*?)<\/script>/i.exec(html)[1];

/** 从 `function name(` 或 `async function name(` 起，按大括号配对取完整函数体 */
function extractFn(src, name) {
  const re = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const m = re.exec(src);
  if (!m) return null;
  let i = src.indexOf('{', m.index + m[0].length - 1);
  if (i < 0) return null;
  let depth = 0, inStr = null, inTpl = false, prev = '';
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (inStr) {
      if (ch === inStr && prev !== '\\') inStr = null;
    } else if (inTpl) {
      if (ch === '`' && prev !== '\\') inTpl = false;
    } else if (ch === '"' || ch === "'") inStr = ch;
    else if (ch === '`') inTpl = true;
    else if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) return src.slice(m.index, j + 1); }
    prev = ch;
  }
  return null;
}

const WANT = ['refreshFitTable', 'applyFittedRatio', 'followRefOn', 'syncFollowRef',
              'fitQuery', 'params', 'syncRatio', 'derivedSize', 'refSizeHint'];
const picked = WANT.map(n => [n, extractFn(code, n)]).filter(([, s]) => s);
const missing = WANT.filter(n => !picked.some(([m]) => m === n));
console.log('提取到的函数:', picked.map(([n]) => n).join(', '));
if (missing.length) console.log('没找到:', missing.join(', '));

// 常量行
const ratioLine = code.split('\n').find(l => l.includes('const RATIO_TBL'));

// ── 最小 DOM ──
function mkEl(id, extra = {}) {
  return Object.assign({
    id, value: '', textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false,
    checked: false, title: '', options: [], tagName: 'INPUT',
    addEventListener() {}, closest: () => null, setSelectionRange() {}, focus() {},
  }, extra);
}
const els = {};
const opts = ['', '1:1', '4:3', '3:4', '3:2', '2:3', '16:9', '9:16']
  .map(v => mkEl('opt', { value: v, textContent: v }));
els.ratio = mkEl('ratio', { tagName: 'SELECT', options: opts, value: '' });
for (const id of ['width', 'height', 'steps', 'seed', 'prompt', 'negative', 'outres',
                  'refsize', 'rationote', 'followref', 'transparent', 'async', 'batch',
                  'bstat', 'bbar', 'blist']) els[id] = mkEl(id);
els.steps.value = '30';
els.width.value = '1024';
els.height.value = '1024';
els.followref.checked = true;

const sandbox = {
  console, URLSearchParams, Blob, atob, btoa, Math, JSON, Date, Number, String, Array, Object,
  parseInt, parseFloat, isNaN, setTimeout, clearTimeout, Promise,
};
sandbox.$ = id => els[id] || (els[id] = mkEl(id));
sandbox.document = { getElementById: id => els[id] || null };
sandbox.URLSearchParams = URLSearchParams;
sandbox.api = p => p;
sandbox.withKey = u => u;
sandbox.authHeaders = h => Object.assign({ Authorization: KEY ? 'Bearer ' + KEY : '' }, h || {});
sandbox.fetch = (url, o) => {
    const full = String(url).startsWith('http') ? String(url) : BASE + String(url);
    const u = new URL(full);
    const lib = u.protocol === 'https:' ? https : http;
    return new Promise((res, rej) => {
      const req = lib.request(u, { method: (o && o.method) || 'GET',
                                   headers: (o && o.headers) || {} }, r => {
        let b = '';
        r.on('data', d => b += d);
        r.on('end', () => res({ ok: r.statusCode < 300, status: r.statusCode,
                                json: async () => JSON.parse(b), text: async () => b }));
      });
      req.on('error', rej);
      if (o && o.body) req.write(o.body);
      req.end();
    });
};
sandbox.logs = [];
sandbox.window = sandbox;
const ctx = vm.createContext(sandbox);

vm.runInContext(ratioLine, ctx);
for (const [, src] of picked) vm.runInContext(src, ctx);
vm.runInContext(`
  var mode = 'edit';
  var files = [];
  var FIT = {};
  var busy = false;
  var AUTHED = true, AUTH_REQUIRED = true;
  function log(m, k){ logs.push((k || '') + ' | ' + String(m).slice(0, 120)); }
  function saveForm(){}
  function showLogin(){}
`, ctx);

(async () => {
  console.log('\n=== 1. refreshFitTable()（真实请求服务端）===');
  await vm.runInContext('refreshFitTable()', ctx);
  const FIT = vm.runInContext('FIT', ctx);
  const keys = Object.keys(FIT);
  console.log('   FIT 键:', keys.join(', ') || '（空！）');
  for (const k of keys) {
    const f = FIT[k];
    if (f) console.log(`   ${k}: fits_as_is=${f.fits_as_is} 建议 ${f.width}x${f.height} (${f.fit_mp}MP)`);
  }
  console.log('\n=== 2. 下拉文案 ===');
  for (const o of els.ratio.options) if (o.value) console.log(`   "${o.textContent}"`);

  console.log('\n=== 3. 模拟：编辑模式 + 有参考图 + 用户选 2:3 ===');
  vm.runInContext('files = [{name: "ref.png", size: 999}];', ctx);
  els.followref.checked = true;
  els.ratio.value = '2:3';
  vm.runInContext('syncRatio(); if (mode === "edit") applyFittedRatio();', ctx);
  console.log('   followref.checked =', els.followref.checked, '（false 才对：跟随会吞掉宽高）');
  console.log('   width =', els.width.value, '  height =', els.height.value);
  console.log('   rationote =', String(els.rationote.textContent || '').slice(0, 100));

  console.log('\n=== 4. 提交时实际发什么 ===');
  const p = vm.runInContext('params()', ctx);
  console.log('   params():', JSON.stringify(p));
  const follow = els.followref.checked;
  const ratioVal = els.ratio.value;
  if (ratioVal) {
    console.log(`   → 发 aspect_ratio=${ratioVal}`);
    const off = vm.runInContext('RATIO_TBL', ctx)[ratioVal];
    console.log(`   → 后端会解析成官方 ${off[0]}x${off[1]}（${(off[0]*off[1]/1e6).toFixed(2)}MP）`);
    const f = FIT[ratioVal];
    console.log(`   → 但本机建议是 ${f ? f.width + 'x' + f.height : '(无)'}`);
  } else {
    console.log(`   跟随参考图 = ${follow}`);
    console.log(follow ? '   → 不发宽高（用 output_resolution 推）'
                       : `   → 发 width=${els.width.value} height=${els.height.value}`);
  }
  console.log('\n=== 5. UI 日志 ===');
  vm.runInContext('logs', ctx).forEach(l => console.log('   ' + l));
})().catch(e => { console.error('出错:', e); process.exit(1); });
