// Native scrolling, one shared animation frame, and a persistent non-personal motion preference.
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let observer,frame=0,currentRoot,paused=false;
try{paused=localStorage.getItem('apna-motion')==='paused';}catch{}
const bar=document.querySelector('.scroll-progress span');
const isStill=()=>paused||reduced.matches;
function update(){
 frame=0;
 const max=document.documentElement.scrollHeight-innerHeight;
 bar.style.transform=`scaleX(${max>0?Math.min(1,Math.max(0,scrollY/max)):0})`;
 document.querySelector('#header')?.classList.toggle('is-scrolled',scrollY>20);
 if(isStill())return;
 const hero=currentRoot?.querySelector('.hero-photo-main>img');
 if(hero&&matchMedia('(min-width: 981px) and (pointer: fine)').matches){
  const rect=hero.closest('.hero-stage').getBoundingClientRect();
  if(rect.bottom>0)hero.style.transform=`scale(1.08) translateY(${Math.min(18,Math.max(-18,-rect.top*.045))}px)`;
 }
 for(const steps of currentRoot?.querySelectorAll('[data-scroll-steps]')||[]){
  const items=[...steps.children];let active=0;items.forEach((el,i)=>{if(el.getBoundingClientRect().top<innerHeight*.72)active=i;});items.forEach((el,i)=>el.classList.toggle('step-active',i<=active));
 }
}
function schedule(){if(!frame)frame=requestAnimationFrame(update);}
function bindPreference(){
 document.documentElement.style.scrollBehavior=isStill()?'auto':'';document.body.classList.add('motion-ready');document.body.classList.toggle('motion-paused',paused);
 const button=document.querySelector('#motion-toggle');
 if(button){button.disabled=reduced.matches;button.setAttribute('aria-pressed',String(paused||reduced.matches));button.querySelector('span').textContent=reduced.matches?'Reduced motion':paused?'Resume motion':'Pause motion';button.onclick=()=>{paused=!paused;try{localStorage.setItem('apna-motion',paused?'paused':'playing');}catch{}initMotion(currentRoot);};}
}
window.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule,{passive:true});
export function initMotion(root){
 currentRoot=root;observer?.disconnect();bindPreference();
 root.querySelectorAll('.reveal').forEach(el=>el.classList.remove('reveal','is-visible'));
 if(!isStill()&&'IntersectionObserver' in window){
  observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target);}},{threshold:.05,rootMargin:'0px 0px -22px 0px'});
  root.querySelectorAll('.service-card,.industry-card,.benefit-card,.news-card,.press-card,.service-detail-title>div,.service-scope,.service-planning,.service-next-steps article,.section-heading,.material-card,.process-step,.split-copy,.local-art,.faq-preview>div,.closing-cta,.value-grid article,.journey article,.story-photo,.discovery-layout,.home-rate-card,.journey-home-intro,.journey-home-step,.home-local-copy,.use-case-card').forEach(el=>{if(el.getBoundingClientRect().top<innerHeight-20)return;el.classList.add('reveal');observer.observe(el);});
 }else{root.querySelectorAll('[data-scroll-steps]>article').forEach(el=>el.classList.add('step-active'));const hero=root.querySelector('.hero-photo-main>img');if(hero)hero.style.transform='none';}
 root.querySelectorAll('.service-card').forEach(card=>{card.onpointermove=e=>{if(isStill()||!matchMedia('(hover:hover) and (pointer:fine)').matches)return;const r=card.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;card.style.setProperty('--rx',((.5-y)*3).toFixed(2)+'deg');card.style.setProperty('--ry',((x-.5)*3).toFixed(2)+'deg');card.style.setProperty('--px',(x*100).toFixed(1)+'%');card.style.setProperty('--py',(y*100).toFixed(1)+'%');};card.onpointerleave=()=>{card.style.setProperty('--rx','0deg');card.style.setProperty('--ry','0deg');};});
 schedule();
}
reduced.addEventListener('change',()=>initMotion(currentRoot||document.querySelector('main')));
