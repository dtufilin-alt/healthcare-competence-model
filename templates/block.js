
const links = Array.from(document.querySelectorAll('nav a'));
const targets = links.map(link => document.getElementById(link.hash.slice(1)));
let queued = false;
function updateNavigation() {
 queued = false;
 let index = 0;
 targets.forEach((target, i) => { if (target.getBoundingClientRect().top <= 110) index = i; });
 if (window.matchMedia('(max-width: 780px)').matches) {
  while (index > 0 && links[index].classList.contains('nav-l2')) index--;
 }
 links.forEach((link, i) => {
  if (i === index) link.setAttribute('aria-current', 'location');
  else link.removeAttribute('aria-current');
 });
}
window.addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(updateNavigation); } }, { passive: true });
window.addEventListener('resize', updateNavigation);
updateNavigation();
