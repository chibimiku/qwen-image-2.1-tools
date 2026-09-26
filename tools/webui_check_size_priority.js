// 核对 index.html 里的"尺寸优先级"：跟随参考图 > 档位 > 手填宽高。
//
// 这个 bug 修过一次又一版：以前档位判在前，导致"跟随参考图"开着时选档位会
// 悄悄覆盖掉跟随 —— 界面显示跟随中，实际按档位出图。所以用静态核对把它钉住。
//
// 用法：node tools/webui_check_size_priority.js
//   可选：node tools/webui_check_size_priority.js http://127.0.0.1:16006 <key>  （顺带查活的 /v1/fit）

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

const html = fs.readFileSync(path.join(__dirname, '..', 'service', 'ui', 'index.html'), 'utf8');
let bad = 0;
const ok = (cond, msg, extra) => {
  console.log(`  [${cond ? 'OK' : 'FAIL'}] ${msg}${extra ? ' — ' + extra : ''}`);
  if (!cond) bad++;
};

console.log('=== 1. 提交逻辑：跟随必须排在档位前面 ===');
// 按标记切开，取"到下一个 request_id 追加为止"的整段，避免被块内第一个 } 截断
const blocks = [];
const MARK = 'const follow = followRefOn();';
let from = 0;
for (;;) {
  const i = html.indexOf(MARK, from);
  if (i < 0) break;
  const seg = html.slice(i, i + 600);
  const cut = seg.indexOf("fd.append('request_id'");
  blocks.push(cut > 0 ? seg.slice(0, cut) : seg);
  from = i + MARK.length;
}
ok(blocks.length === 2, `找到 2 处尺寸分支（实际 ${blocks.length}）`, `单张 + 批量`);

for (const [n, b] of blocks.entries()) {
  const iFollow = b.indexOf('if (follow)');
  const iRatio = b.indexOf("aspect_ratio");
  const iWH = b.indexOf("fd.append('width'");
  ok(iFollow > -1, `第 ${n + 1} 处有 if (follow) 分支`);
  ok(iRatio > -1, `第 ${n + 1} 处有 aspect_ratio 分支`);
  ok(iFollow > -1 && iRatio > -1 && iFollow < iRatio,
     `第 ${n + 1} 处：follow 在 ratio 之前`, `follow@${iFollow} ratio@${iRatio}`);
  ok(/if \(follow\) \{[\s\S]*?else if \(\$\('ratio'\)\.value\)/.test(b),
     `第 ${n + 1} 处是 if(follow) → else if(ratio) → else 宽高`);
  ok(iWH > iRatio || iWH === -1,
     `第 ${n + 1} 处：手填宽高排在最后`, `width@${iWH} ratio@${iRatio}`);
}

console.log('\n=== 2. 跟随开启时，档位要被置灰（而不是静默清空）===');
const syncFn = /function syncFollowRef\(\)\{[\s\S]*?\n\}/.exec(html)[0];
ok(/sel\.disabled = on/.test(syncFn), 'syncFollowRef 里对 ratio 设了 disabled');
ok(!/\$\('ratio'\)\.value = ''/.test(syncFn),
   '不再静默清空 ratio.value（那会让用户一选就悄悄切模式）');
ok(/sel\.title = on/.test(syncFn), '置灰时给了 title 解释');

console.log('\n=== 3. 跟随开启时，宽高也被置灰 ===');
ok(/el\.disabled = on/.test(syncFn), 'width/height 被 disable');
ok(/\.45/.test(syncFn), '有视觉上的灰化（opacity）');

console.log('\n=== 4. 取消勾选后要能恢复可用 ===');
ok(/sel\.disabled = on;/.test(syncFn) && !/disabled = true/.test(syncFn),
   '用的是 on 变量而不是写死 true，取消勾选会恢复');

// 可选：活的 /v1/fit
const BASE = process.argv[2];
const KEY = process.argv[3] || '';
if (BASE) {
  console.log('\n=== 5. 活的 /v1/fit（确认服务端还在正常给建议）===');
  const u = new URL(BASE + '/v1/fit?all_ratios=true&steps=30');
  const lib = u.protocol === 'https:' ? https : http;
  const req = lib.request(u, { headers: { Authorization: 'Bearer ' + KEY } }, r => {
    let b = '';
    r.on('data', d => b += d);
    r.on('end', () => {
      try {
        const j = JSON.parse(b);
        const e = j.ratios['2:3'].edit;
        console.log(`  2:3/edit → fits_as_is=${e.fits_as_is} 建议 ${e.width}x${e.height}`);
        ok(e.fits_as_is === false || e.fits_as_is === true, 'fits_as_is 有值');
      } catch (err) { ok(false, '解析失败', err.message); }
      console.log(bad ? `\n${bad} 项失败 ❌` : '\n全部通过 ✅');
      process.exit(bad ? 1 : 0);
    });
  });
  req.on('error', e => { ok(false, '请求失败', e.message); process.exit(1); });
  req.end();
} else {
  console.log(bad ? `\n${bad} 项失败 ❌` : '\n全部通过 ✅');
  process.exit(bad ? 1 : 0);
}
