const reportLinks = Array.from(document.querySelectorAll('.report-toc a'));
const reportTargets = reportLinks.map(link => document.getElementById(link.hash.slice(1)));
let reportQueued = false;
function updateReportNavigation() {
 reportQueued = false;
 let index = 0;
 reportTargets.forEach((target, i) => {
  if (target && target.getBoundingClientRect().top <= 120) index = i;
 });
 if (window.matchMedia('(max-width: 780px)').matches) {
  while (index > 0 && reportLinks[index].classList.contains('nav-l2')) index--;
 }
 reportLinks.forEach((link, i) => {
  if (i === index) link.setAttribute('aria-current', 'location');
  else link.removeAttribute('aria-current');
 });
}
window.addEventListener('scroll', () => {
 if (!reportQueued) { reportQueued = true; requestAnimationFrame(updateReportNavigation); }
}, {passive: true});
window.addEventListener('resize', updateReportNavigation);
updateReportNavigation();
