
const panels = Array.from(document.querySelectorAll('.block-panel'));
const tabs = Array.from(document.querySelectorAll('.block-tab'));
let activePanel = panels[0];
let queued = false;
const blockTabs = document.querySelector('.block-tabs');
function showActiveTab() {
 const link = tabs.find(item => item.hash === '#' + activePanel.id);
 if (link && blockTabs.scrollWidth > blockTabs.clientWidth) {
  blockTabs.scrollLeft = Math.max(0, link.offsetLeft - (blockTabs.clientWidth - link.offsetWidth) / 2);
 }
}
function updateTabsHeight() {
 document.documentElement.style.setProperty('--block-tabs-height', blockTabs.getBoundingClientRect().height + 'px');
 showActiveTab();
}
updateTabsHeight();
if ('ResizeObserver' in window) new ResizeObserver(updateTabsHeight).observe(blockTabs);
window.addEventListener('resize', updateTabsHeight);
function updateNavigation() {
 queued = false;
 const links = Array.from(activePanel.querySelectorAll('.block-toc a'));
 let index = 0;
 links.forEach((link, i) => {
  const target = document.getElementById(link.hash.slice(1));
  if (target && target.getBoundingClientRect().top <= blockTabs.getBoundingClientRect().bottom + 50) index = i;
 });
 if (window.matchMedia('(max-width: 780px)').matches) {
  while (index > 0 && links[index].classList.contains('nav-l2')) index--;
 }
 links.forEach((link, i) => {
  if (i === index) link.setAttribute('aria-current', 'location');
  else link.removeAttribute('aria-current');
 });
}
function activate(panel) {
 activePanel = panel;
 panels.forEach(item => { item.hidden = item !== panel; });
 tabs.forEach(link => {
  if (link.hash === '#' + panel.id) link.setAttribute('aria-current', 'page');
 else link.removeAttribute('aria-current');
 });
 showActiveTab();
 updateNavigation();
}
function route(scroll) {
 let target;
 try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) {}
 const panel = target && target.closest('.block-panel');
 if (panel) activate(panel);
 else if (!location.hash) activate(panels[0]);
 if (scroll && target) requestAnimationFrame(() => target.scrollIntoView({ block: 'start' }));
}
tabs.forEach(link => link.addEventListener('click', event => {
 if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
 event.preventDefault();
 if (location.hash !== link.hash) history.pushState(null, '', link.hash);
 route(true);
}));
window.addEventListener('hashchange', () => route(true));
window.addEventListener('popstate', () => route(true));
window.addEventListener('scroll', () => {
 if (!queued) { queued = true; requestAnimationFrame(updateNavigation); }
}, { passive: true });
window.addEventListener('resize', updateNavigation);
activate(panels[0]);
route(Boolean(location.hash));
