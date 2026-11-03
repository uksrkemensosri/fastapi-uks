// Catch HTML script terminators accidentally inserted into print templates.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('app/ui/index.html', 'utf8');
let checked = 0;
for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  if (/\bsrc=/.test(match[1])) continue;
  new vm.Script(match[2], {filename: 'dashboard-inline-' + checked});
  checked++;
}
assert.ok(checked > 0);
assert.equal((html.match(/<script src="\/ui\/assets\/fasyankes-dashboard\.js\?v=2"><\/script>/g)||[]).length, 1);
console.log(`Dashboard: ${checked} inline scripts parsed successfully`);
