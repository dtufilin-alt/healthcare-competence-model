const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/tmp/nat-ui/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const server=spawn(path.join(root,'.venv/bin/python'),['tests/serve_browser.py'],{cwd:root,stdio:'ignore'});
const url='http://127.0.0.1:8767';
const artifacts=path.join(root,'test-artifacts');fs.mkdirSync(artifacts,{recursive:true});
let browser;
async function check(condition,message){assert(await condition,message)}
(async()=>{
 for(let i=0;i<60;i++){try{if((await fetch(url)).ok)break}catch{}await new Promise(r=>setTimeout(r,200))}
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/home/denistyufilin/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell',args:['--no-sandbox']});
 const errors=[];
 const ac=await browser.newContext({viewport:{width:1440,height:1000}}),ec=await browser.newContext({viewport:{width:1440,height:1000}});
 const a=await ac.newPage(),e=await ec.newPage();
 for(const p of [a,e]){p.on('pageerror',err=>errors.push(err.message));p.on('response',r=>{if(r.status()>=500)errors.push(`HTTP ${r.status()} ${r.url()}`)})}
 await a.goto(url);await a.getByRole('button',{name:'Попробовать демоверсию →'}).waitFor();await a.screenshot({path:path.join(artifacts,'01-landing.png'),fullPage:true});
 await a.getByRole('button',{name:'Кабинет организатора →'}).click();
 await a.locator('input[name=key]').fill('browser-test-only');await a.getByRole('button',{name:'Войти',exact:true}).click();
 await a.getByRole('button',{name:'Создать приглашение →'}).click();
 await a.locator('input[name=name]').fill('Тестовый эксперт');await a.locator('input[name=email]').fill('expert@example.org');await a.getByRole('button',{name:'Создать персональную ссылку'}).click();
 const invite=await a.locator('#invite-link').inputValue();
 await e.goto(invite);
 await e.locator('#profile-form').waitFor();await e.screenshot({path:path.join(artifacts,'07-profile.png'),fullPage:true});
 await e.locator('input[name=organization]').fill('Демонстрационная организация');
 await e.locator('input[name=position]').fill('Руководитель');await e.locator('input[name=years]').fill('12');
 await e.locator('select[name=context]').selectOption('organization');await e.locator('input[name=levels]').fill('Подразделение, организация');
 await e.locator('textarea[name=involvement]').fill('Не участвовал; заинтересованности нет');await e.locator('input[name=eligible_blocks][value="1"]').check();await e.locator('input[name=eligible_blocks][value="2"]').check();await e.locator('input[name=consent]').check();
 await e.getByRole('button',{name:'Сохранить и продолжить →'}).click();await e.getByRole('button',{name:'Начать оценку →'}).waitFor();await e.screenshot({path:path.join(artifacts,'08-instructions.png'),fullPage:true});await e.getByRole('button',{name:'Начать оценку →'}).click();
 await e.locator('input[name=relevance][value="4"]').check();await e.locator('input[name=clarity][value="3"]').check();await e.locator('input[name=observability][value="4"]').check();
 await e.locator('[data-comment="knows:0"]').click();await e.locator('#comment-form textarea').fill('Уточнить границы ответственности.');await e.getByRole('button',{name:'Добавить комментарий'}).click();
 await e.waitForFunction(()=>document.querySelector('#save-status')?.textContent==='Все изменения сохранены');
 await check(e.locator('#progress-label').textContent().then(t=>t==='Заполнено 1 из 8'),'progress updates without navigation');
 await e.locator('details.example summary').first().click();await check(e.locator('details.example p').first().isVisible(),'full example remains available');await e.locator('details.example summary').first().click();
 await e.screenshot({path:path.join(artifacts,'02-expert-card.png'),fullPage:true});
 await e.reload();await e.getByRole('button',{name:'Продолжить оценку',exact:true}).click();await e.locator('[data-go="b1:participants"]').click();
 await check(e.locator('input[name=relevance][value="4"]').isChecked(),'rating survives reload');await check(e.getByText('Уточнить границы ответственности.',{exact:true}).isVisible(),'comment survives reload');
 await e.setViewportSize({width:390,height:844});await e.screenshot({path:path.join(artifacts,'03-mobile.png'),fullPage:true});
 for(const width of [390,320]){await e.setViewportSize({width,height:844});await check(e.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow')}
 await e.locator('.nav-fold summary').click();await check(e.locator('[data-go="profile"]').isVisible(),'mobile navigation expands');
 await e.setViewportSize({width:1440,height:1000});
 async function completeCards(page){
   for(let i=0;i<100;i++){
     if(await page.locator('#submit').count())break;
     const radios=page.locator('#content input[type=radio][value="4"]');
     for(let j=0;j<await radios.count();j++)await radios.nth(j).check();
     await page.locator('#next').click();
   }
   await page.locator('#submit').click();await page.locator('#confirmation button[value=yes]').click();
   await page.getByText('Спасибо, ваши ответы приняты',{exact:true}).waitFor();
 }
 await completeCards(e);
 await a.locator('#admin-refresh').click();await a.getByRole('button',{name:'Оценки и замечания',exact:true}).click();await a.locator('#context-filter').selectOption('organization');
 await a.getByText('Уточнить границы ответственности.',{exact:true}).waitFor();assert.equal(await a.locator('.group-row').count(),8);await a.screenshot({path:path.join(artifacts,'04-organizer-results.png'),fullPage:true});
 await a.getByRole('button',{name:'Раунды и версии',exact:true}).click();await a.locator('input[name=target]').first().check();await a.locator('textarea[name=rationale]').fill('Повторная оценка: уточнить границы ответственности в первом знании. Редакция пока сохранена для обсуждения.');
 await a.getByRole('button',{name:'Зафиксировать версию и открыть второй раунд'}).click();await a.locator('#confirmation button[value=yes]').click();await a.locator('#open-weights').waitFor();
 await e.locator('#refresh').click();await e.locator('[data-go="b1:participants"]').click();await e.getByText('Что изменилось и почему',{exact:true}).waitFor();await e.screenshot({path:path.join(artifacts,'05-round-two.png'),fullPage:true});
 await completeCards(e);
 await a.locator('#admin-refresh').click();await a.locator('#open-weights').click();await a.locator('#confirmation button[value=yes]').click();await a.locator('#close-study').waitFor();
 await e.locator('#refresh').click();await e.locator('#equal').click();await e.locator('#confirmation button[value=yes]').click();await e.locator('#preview-weights').click();
 await e.getByText('Ваши относительные приоритеты',{exact:true}).waitFor();await check(e.locator('.weight-line').count().then(n=>n===8),'8 weight results');
 await e.screenshot({path:path.join(artifacts,'06-bwm.png'),fullPage:true});
 await e.locator('#submit-weights').click();await e.locator('#confirmation button[value=yes]').click();await e.getByText('Приоритеты отправлены. Спасибо!',{exact:true}).waitFor();
 await a.getByRole('button',{name:'Приоритеты BWM',exact:true}).click();await a.locator('#round-filter').selectOption({label:'Раунд 2 · версия 2'});await a.getByText('12.5%',{exact:true}).first().waitFor();
 assert.deepEqual(errors,[]);console.log('PASS: invitation, profile, 8 cards in 2 assigned blocks, comment, reload, 320/390px, round 2, BWM, admin results; no JS or server errors');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close();server.kill()});
