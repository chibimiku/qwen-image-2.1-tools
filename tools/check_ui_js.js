// 抽取 index.html 里的所有 <script> 块，用 node 做语法检查 + 关键符号自检
const fs = require('fs');
const path = process.argv[2];
const html = fs.readFileSync(path, 'utf8');

const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
console.log('script blocks:', blocks.length);
let bad = 0;
blocks.forEach((m, i) => {
  const code = m[1];
  const line = html.slice(0, m.index).split('\n').length;
  // 记录脚本在 HTML 中的起始行，便于把报错行号换算回来
  try {
    new (require('vm').Script)(code, { filename: `block${i}.js` });
    console.log(`  block ${i} (html line ${line}, ${code.length} chars): syntax OK`);
  } catch (e) {
    bad++;
    console.log(`  block ${i} (html line ${line}): SYNTAX ERROR -> ${e.message}`);
  }
});

// 关键符号自检
const need = [
  ['function renderChips', 1], ['function insertTag', 1], ['function renderThumbs', 1],
  ['id="chips"', 1], ['id="refhint"', 1], ['class="chips"', 1],
  ['insertTag(', 2],            // 定义处不算 onclick 字符串？实际 1 定义 + n 个 onClick
  ['.chips{', 1], ['.chip{', 1], ['.thumb i{', 1],
];
console.log('--- symbol counts ---');
for (const [s, want] of need) {
  const n = html.split(s).length - 1;
  const flag = want === null ? '' : (n >= want ? 'OK' : 'LOW');
  console.log(`  ${JSON.stringify(s)}: ${n} ${flag}`);
}
// 重复定义检测
for (const fn of ['renderChips', 'insertTag', 'renderThumbs']) {
  const n = (html.match(new RegExp(`function ${fn}\\s*\\(`, 'g')) || []).length;
  console.log(`  def ${fn}(): ${n}${n === 1 ? ' OK' : ' DUPLICATE!'}`);
}

// 新增 UI 元素自检
console.log('--- followref / 阶段进度 元素 ---');
for (const s of ['id="followref"', 'id="refsize"', 'function syncFollowRef',
                 'function refSizeHint', 'function derivedSize', 'function followRefOn']) {
  const n = html.split(s).length - 1;
  console.log(`  ${JSON.stringify(s)}: ${n}${n >= 1 ? ' OK' : ' MISSING!'}`);
}

// 递归风险：A 调 B、B 又调 A —— 这种死递归只会在浏览器里炸，必须静态拦下。
// 两个坑都踩过，所以这里：① 先剥注释（注释里提到函数名会被当成调用）；
// ② 用"函数起始位置数组"切片，而不是找 '\nfunction ' —— 函数之间的注释块会让
// 朴素切片把下一个函数的声明也包进来，于是 batchCancelPending 里凭空"出现"
// 了 batchStop，误报成环。
const code = blocks.map(m => m[1]).join('\n')
  .replace(/\/\*[\s\S]*?\*\//g, ' ')       // 块注释
  .replace(/(^|[^:])\/\/[^\n]*/g, '$1');   // 行注释（[^:] 避开 https:// ）

const fns = [...code.matchAll(/function\s+([A-Za-z_$][\w$]*)\s*\(/g)];
const FNS = fns.map(m => m[1]);
const startAt = new Map(fns.map((m, i) => [m[1], m.index]));
const endAt = new Map(fns.map((m, i) => [m[1], i + 1 < fns.length ? fns[i + 1].index : code.length]));
const calls = {};
for (const fn of FNS) {
  const seg = code.slice(startAt.get(fn), endAt.get(fn));
  calls[fn] = new Set(FNS.filter(o => o !== fn && new RegExp(`\\b${o}\\s*\\(`).test(seg)));
}
console.log('--- 互相调用检测（A→B 且 B→A 就是死递归） ---');
let cycles = 0;
for (const a of FNS) for (const b of (calls[a] || [])) {
  if (calls[b] && calls[b].has(a) && a < b) {
    cycles++;
    console.log(`  CYCLE: ${a}() <-> ${b}()`);
  }
}
console.log(cycles ? `  ${cycles} 处互相调用 —— 确认是否有终止条件！` : '  无互相调用 OK');

process.exit(bad ? 1 : 0);
