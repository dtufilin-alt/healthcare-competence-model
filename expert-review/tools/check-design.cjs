const fs=require('node:fs');const assert=require('node:assert/strict');
const css=fs.readFileSync('static/styles.css','utf8');const tokens=fs.readFileSync('static/vendor/mednet/tokens.css','utf8');
assert(!/#[\da-f]{3,8}\b|\b(?:rgb|hsl|oklch)a?\(/i.test(css),'Use semantic Mednet tokens, not raw colors');
for(const [,name] of css.matchAll(/var\((--mn-[\w-]+)\)/g))assert(tokens.includes(name+':'),`Missing token ${name}`);
for(const [,file] of fs.readFileSync('static/vendor/mednet/fonts.css','utf8').matchAll(/url\(\.\/([^)]*)\)/g))assert(fs.existsSync('static/vendor/mednet/'+file),`Missing font ${file}`);
console.log('PASS: semantic design tokens and all local font assets');
