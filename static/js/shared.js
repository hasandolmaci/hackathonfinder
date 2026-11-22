export const kinds = {hackathon:'Hackathons',game_jam:'Game jams',ctf:'CTFs',coding_competition:'Coding competitions',ideathon:'Ideathons'};
export const sourceInfo = [ ['devpost','Devpost','devpost.com'],['mlh','MLH','mlh.com'],['devfolio','Devfolio','devfolio.co'],['unstop','Unstop','unstop.com'],['hackclub','Hack Club','hackclub.com'],['taikai','TAIKAI','taikai.network'],['hackerearth','HackerEarth','hackerearth.com'],['hackathoncom','Hackathon.com','hackathon.com'],['ethglobal','ETHGlobal','ethglobal.com'],['lablab','lablab.ai','lablab.ai'],['kaggle','Kaggle','kaggle.com'],['ctftime','CTFtime','ctftime.org'],['itchio','itch.io','itch.io'],['luma','Luma','luma.com'],['meetup','Meetup','meetup.com'] ].map(([id,name,host])=>({id,name,host,status:'never',count:0,error:null}));
export const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function safeURL(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:'#';}catch{return '#';}}
export function sourceName(id){return sourceInfo.find(s=>s.id===id)?.name || id;}
export function favicon(id,url){if(new URLSearchParams(location.search).get('mock')==='1')return `<span class="mock-icon" aria-hidden="true">${esc(sourceName(id).slice(0,1))}</span>`;let host=sourceInfo.find(s=>s.id===id)?.host;try{host ||= new URL(url).hostname;}catch{}return `<img class="favicon" src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(host||'example.com')}&amp;sz=32" alt="" title="${esc(sourceName(id))}" loading="lazy" referrerpolicy="no-referrer">`;}
export function formatName(value){return {online:'Online','in-person':'In-person',hybrid:'Hybrid',unknown:'Not specified'}[value]||'Not specified';}
export function filterEvents(events,state){const today=new Date();today.setHours(0,0,0,0);const cutoff=new Date(today);cutoff.setDate(cutoff.getDate()+Number(state.days));const q=(state.q||'').toLowerCase().trim();return events.filter(e=>{const start=e.start?new Date(e.start):null,end=e.end?new Date(e.end):null;return state.kinds.includes(e.kind)&&(!state.format||e.format===state.format)&&(!start||start>=today||(end&&end>=today))&&(state.days==='all'||!start||start<cutoff)&&(!q||[e.title,e.description,e.location,e.organizer,...(e.tags||[])].join(' ').toLowerCase().includes(q));});}
function startKey(e,now){if(!e.start)return null;const s=Date.parse(e.start);if(s>=now)return s;/* already running: after all upcoming, by end date */const end=e.end?Date.parse(e.end):s;return 1e15+end;}
export function sortEvents(events,sort='start',order='asc'){const now=Date.now();return [...events].sort((a,b)=>{const value=e=>sort==='start'?startKey(e,now):sort==='new'?Date.parse(e.first_seen):e[{prize:'prize_usd',distance:'distance_km'}[sort]||sort];let av=value(a),bv=value(b);if(av==null||!Number.isFinite(av))return bv==null||!Number.isFinite(bv)?a.title.localeCompare(b.title):1;if(bv==null||!Number.isFinite(bv))return -1;return (av-bv)*(order==='desc'?-1:1)||a.title.localeCompare(b.title);});}
export const number = value => value==null?'—':Number(value).toLocaleString();
export function dateLabel(value){return value?new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Date TBA';}
export function timeUntil(value){if(!value)return 'TBA';const hours=(Date.parse(value)-Date.now())/36e5;return hours<=0?'Live':hours<1?'<1h':hours<24?`${Math.ceil(hours)}h`:`${Math.ceil(hours/24)}d`;}
export function preserveMockLinks(){if(new URLSearchParams(location.search).get('mock')!=='1')return;document.querySelectorAll('a[href]').forEach(a=>{const u=new URL(a.href);if(u.origin===location.origin){u.searchParams.set('mock','1');a.href=u.href;}});}
export async function getJSON(path,options={}){const response=await fetch(path,{...options,headers:{Accept:'application/json',...options.headers}});if(!response.ok)throw new Error(`Unable to fetch data (${response.status}).`);return response.json();}

export function timeAgo(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return 'not yet';
    const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 60000));
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
    const days = Math.floor(hours / 24);
    return `${days} ${days === 1 ? 'day' : 'days'} ago`;
}

export const locationKey = 'hackfinder.location';
export function savedLocation(){try{const p=JSON.parse(localStorage.getItem(locationKey));return p&&Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&Math.abs(p.lat)<=90&&Math.abs(p.lon)<=180?p:null;}catch{return null;}}
