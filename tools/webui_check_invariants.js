// 汇总 UI 必须守住的几条不变量（都是之前真实踩过的 bug）。
//
// 用法：node tools/webui_check_invariants.js
// 加参数时顺带跑一下，免得改回去。

const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'service', 'ui', 'index.html'), 'utf8');
let bad = 0;
const ok = (cond, msg, extra) => {
  console.log(`  [${cond ? 'OK' : 'FAIL'}] ${msg}${extra ? ' — ' + extra : ''}`);
  if (!cond) bad++;
};
const fnBody = (name, len = 1400) => {
  const i = html.indexOf(`function ${name}(`);
  if (i < 0) return '';
  return html.slice(i, i + len);
};

console.log('=== A. 会话失效处理（服务重启后不卡、输入不被清空）===');
{
  const sl = /function showLogin\(msg\)\{[\s\S]*?\n\}/.exec(html);
  ok(!!sl, '找到 showLogin');
  const body = sl ? sl[0] : '';
  ok(/if \(inp && !wasOpen\)/.test(body),
     'showLogin 只在**首次弹出**时清空输入框（否则每个后到的 401 都会清掉用户正在敲的内容）');
  ok(!/if \(inp\)\{ inp\.value = ''; setTimeout/.test(body),
     '没有无条件清空输入框的旧写法');

  const o4 = /async function on401\(\)\{[\s\S]*?\n\}/.exec(html);
  ok(!!o4, '找到 on401');
  const b4 = o4 ? o4[0] : '';
  ok(/_authProbe/.test(b4), 'on401 用 _authProbe 去重（并发 401 只探测一次）');
  ok(/_authWarnedAt|10000/.test(b4), 'on401 的日志有节流（不会刷屏）');
}

console.log('\n=== B. 401 不重试（避免请求风暴 / 死循环）===');
{
  const getB = /async function get\(url\)\{[\s\S]*?\n\}/.exec(html);
  const postB = /async function post\(url, body\)\{[\s\S]*?\n\}/.exec(html);
  for (const [name, m] of [['get', getB], ['post', postB]]) {
    const b = m ? m[0] : '';
    ok(b.includes('await on401()'), `${name}() 里 await 了 on401`);
    ok(!/on401\(\)\)\s*return (get|post)\(/.test(b),
       `${name}() 不再"401 就递归重发"`);
  }
}

console.log('\n=== C. 轮询标志用 finally 清（否则异常后永久停摆）===');
{
  const p = fnBody('makePoller', 900);
  ok(/finally\s*\{[\s\S]{0,80}ticking = false/.test(p),
     'makePoller 的 ticking 在 finally 里清（401/网络异常后还能继续轮询）');
}

console.log('\n=== D. 尺寸优先级：跟随 > 档位 > 手填 ===');
{
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
  ok(blocks.length === 2, '找到两处尺寸分支（单张 + 批量）', `实际 ${blocks.length}`);
  for (const [n, b] of blocks.entries()) {
    ok(b.indexOf('if (follow)') < b.indexOf('aspect_ratio'),
       `第 ${n + 1} 处 follow 排在 ratio 之前`);
  }
  const sf = /function syncFollowRef\(\)\{[\s\S]*?\n\}/.exec(html);
  ok(sf && /sel\.disabled = on/.test(sf[0]), '跟随开启时档位被置灰');
  ok(sf && !/\$\('ratio'\)\.value = ''/.test(sf[0]), '不再静默清空档位取值');
}

console.log('\n=== E. 登录框 / 会话条不会自我触发 ===');
{
  ok(!/setInterval\(\s*refreshSessionBar\s*,\s*[0-9]{1,3}\)/.test(html),
     '会话条刷新间隔不小于 1 秒（不是高频轮询）');
  const rsb = /async function refreshSessionBar\(\)\{[\s\S]*?\n\}/.exec(html);
  ok(rsb && /_authProbe/.test(rsb[0]), 'refreshSessionBar 会复用 on401 的探测（不叠请求）');
}

console.log(bad ? `\n${bad} 项失败 ❌` : '\n全部通过 ✅');
process.exit(bad ? 1 : 0);
