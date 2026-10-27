const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const dest = path.join(root, 'static/vendor/mednet');
fs.mkdirSync(dest, {recursive: true});
for (const [from, to] of [
  ['tokens/dist/tokens.css', 'tokens.css'],
  ['css/dist/fonts.css', 'fonts.css'],
  ['css/dist/fonts', 'fonts'],
  ['tokens/LICENSE', 'LICENSE-tokens'],
  ['css/LICENSE', 'LICENSE-css'],
  ['css/THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md'],
]) fs.cpSync(path.join(root, 'node_modules/@mednet', from), path.join(dest, to), {recursive: true});
console.log('Mednet tokens and fonts copied from pinned packages.');
