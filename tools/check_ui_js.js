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
process.exit(bad ? 1 : 0);
