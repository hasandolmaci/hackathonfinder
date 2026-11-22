import {sourceInfo,filterEvents,sortEvents,getJSON,categoryNames,typeNames,regionNames} from './shared.js';
export const isMock = new URLSearchParams(location.search).get('mock')==='1';
const titles=['Open Source Weekend','Agents for Good','Build the Next Internet','Climate Code Collective','Midnight Makers','Future of Finance','The Local AI Hack','Campus Builders','Creative Machines','Hack the Everyday','Better Cities Buildathon','Zero to One Weekend','Small Tools, Big Ideas','HealthTech Hack','The Open Data Challenge','Reimagine Learning','Build Without Borders','Weekend on the Web','The Accessibility Sprint','Green Grid Hack','AI Studio Weekend','Hardware & Humans','The Community Build','Next Chapter Hack','Pixel Planet Jam','One Button Game Jam','Cozy Worlds Jam','Tiny Adventure Jam','Signal Capture CTF','Midnight Security CTF','Flag Hunters CTF','Codebreakers CTF','Forecast the Future','Data for Nature','Algorithm Arena','Vision Challenge','Ideas for Tomorrow','Future Cities Ideathon','Circular Economy Pitch','Moonshot Ideas','Fireside: Funding Open Source','Panel: AI Safety in Practice','Amsterdam Builders Meetup','Hack Night: Open Social Evening','Intro to LLM Agents Workshop','Rust Masterclass','Pre-Hackathon: Meet Your Team','Hackathon Kick-off & Info Session'];
const now=Date.now(), hour=36e5;
const events=titles.map((title,i)=>{const kind=i>=40?['talk','talk','meetup','meetup','workshop','workshop','info_session','info_session'][i-40]:i<24?'hackathon':i<28?'game_jam':i<32?'ctf':i<36?'coding_competition':'ideathon';const source=i<24?sourceInfo[i%10]:sourceInfo[kind==='game_jam'?12:kind==='ctf'?11:kind==='coding_competition'?10:3];const offset=i<7?i*13+1:i<24?(i-6)*30:(i-24)*17+3;const format=['online','in-person','online','hybrid'][i%4];return {source:source.id,source_id:String(i),url:`https://${source.host}/sample-event-${i+1}`,title,description:`A sample ${kind.replaceAll('_',' ')} for curious builders.`,start:i===23?null:new Date(now+(i===0?-24:offset)*hour).toISOString(),end:new Date(now+(offset+72)*hour).toISOString(),format,location:format==='online'?null:['Berlin, Germany','London, UK','San Francisco, US','Bengaluru, India'][i%4],prize:i%6===0?null:`$${((i%8+1)*2500).toLocaleString('en-US')}`,prize_usd:i%6===0?null:(i%8+1)*2500,participants:i%7===0?null:48+i*37,kind,also_on:i%5===0?['luma','meetup']:[],tags:i%2?['ai','open-source']:['climate','student'],fetched_at:new Date(now-i*hour).toISOString()};});
const eventCats=[['opensource','devtools'],['ai','social'],['web3','fintech'],['climate','data'],['hardware','robotics'],['fintech','mobile'],['ai','devtools','cloud'],['education','social'],['design','xr'],['web','mobile'],['social','climate'],['ai','space'],['devtools','opensource'],['health','data'],['data','social'],['education','ai'],['social','web'],['web','design'],['design','social'],['climate','hardware'],['ai','cloud'],['hardware','robotics','xr'],['social','education'],['devtools','web'],['gaming','xr'],['gaming'],['gaming','design'],['gaming','mobile'],['security'],['security','cloud'],['security','opensource'],['security','hardware'],['data','ai'],['data','climate'],['data','ai','web'],['ai','xr'],['social','education'],['climate','social'],['climate','fintech'],['space','hardware'],['opensource'],['ai'],['social','devtools'],['social'],['ai','devtools'],['devtools'],['social','web'],['web']];
const places=[
    {name:'Amsterdam',country:'Netherlands',country_code:'NL',lat:52.3676,lon:4.9041,population:921402},
    {name:'Amstelveen',country:'Netherlands',country_code:'NL',lat:52.3008,lon:4.8636,population:95007},
    {name:'Berlin',country:'Germany',country_code:'DE',lat:52.52,lon:13.405,population:3645000},
    {name:'London',country:'United Kingdom',country_code:'GB',lat:51.5074,lon:-0.1278,population:8982000},
    {name:'Paris',country:'France',country_code:'FR',lat:48.8566,lon:2.3522,population:2161000},
    {name:'San Francisco',country:'United States',country_code:'US',lat:37.7749,lon:-122.4194,population:873965},
    {name:'Bengaluru',country:'India',country_code:'IN',lat:12.9716,lon:77.5946,population:8443675},
    {name:'São Paulo',country:'Brazil',country_code:'BR',lat:-23.5505,lon:-46.6333,population:12330000}
];
const regionOf={NL:'europe',DE:'europe',GB:'europe',FR:'europe',US:'north_america',IN:'asia',BR:'latin_america'};
const weights={hackathon:[30,20,20,20,10],ideathon:[30,20,20,20,10],game_jam:[25,35,10,15,15],ctf:[40,25,10,10,15],coding_competition:[25,20,40,0,15],talk:[30,20,20,20,10],meetup:[30,20,20,20,10],workshop:[30,20,20,20,10],info_session:[30,20,20,20,10]};
const dimIds=['organizer','community','rewards','support','accessibility'];
const methodology={version:'demo-1',dimensions:dimIds.map((id,i)=>({id,name:['Organizer','Community','Rewards','Support','Accessibility'][i],weight_by_kind:Object.fromEntries(Object.entries(weights).map(([k,w])=>[k,w[i]])),inputs:[['Reviewed organizer reputation','Verified, featured, MLH membership','Recurring editions'],['Registrations, guests, RSVPs, teams','Source and kind percentiles'],['Cash prizes in USD, logarithmic scale','Capped non-cash rewards'],['Sponsors, mentors, travel support','Hiring, food and swag'],['Free entry, open eligibility','Online or hybrid access']][i]})),tiers:[{id:'great',name:'Great',min:80,max:100},{id:'good',name:'Good',min:60,max:79},{id:'fair',name:'Fair',min:40,max:59},{id:'low',name:'Low',min:0,max:39},{id:'unknown',name:'Unknown',range:'Not enough info'}],reputation_tiers:{A:['ETHGlobal (sample)','MLH (sample)'],B:['Community organizers (sample)']},notes:['Demo formula and sample reputation entries; live methodology comes from the API.','Missing data is shrunk toward a source/kind prior, never scored as zero.','Evidence below 30 produces no numeric score. Confidence reflects observed evidence.','Duplicate participant counts are never summed. Dates and location do not affect the score.']};
for(const [i,e] of events.entries()){
    const p=places[Math.floor(i/4)%places.length],score=i%7===0?null:[88,72,51,32][(i+Math.floor(i/4))%4];
    Object.assign(e,{score,score_tier:score==null?'unknown':score>=80?'great':score>=60?'good':score>=40?'fair':'low',score_confidence:score==null||i%3===0?'low':i%3===1?'high':'medium',lat:e.format==='online'?null:p.lat+(i%3)*0.08,lon:e.format==='online'?null:p.lon,first_seen:new Date(now-i*hour).toISOString(),score_detail:{dims:Object.fromEntries(dimIds.map((key,j)=>[key,Math.min(100,(score??45)+j*3-6)])),weights:Object.fromEntries(dimIds.map((key,j)=>[key,weights[e.kind][j]])),evidence:score==null?20:i%3===0?35:i%3===1?90:65,reasons:['Recurring community event','Published prizes and participation figures','Open to independent builders'],missing:['Travel support','Mentor details'],version:'demo-1'}});
    if(e.format!=='online')e.location=`${p.name}, ${p.country}`;
    Object.assign(e,{country_code:e.format==='online'?null:p.country_code,country_name:e.format==='online'?null:p.country,region:e.format==='online'?'online':regionOf[p.country_code]});
    e.categories=eventCats[i];
    e.flags=[i%2===0&&'student',i%3===0&&'beginner',e.prize_usd>0&&'cash_prize',i%5===1&&'travel',e.format!=='online'&&i%4===3&&'weekend',i<8&&'new'].filter(Boolean);
}
function distance(a,b,c,d){const rad=n=>n*Math.PI/180,x=Math.sin(rad(c-a)/2)**2+Math.cos(rad(a))*Math.cos(rad(c))*Math.sin(rad(d-b)/2)**2;return 6371*2*Math.asin(Math.min(1,Math.sqrt(x)));}
function sources() {
    return sourceInfo.map((s, i) => ({
        ...s, method: i < 10 ? 'api' : 'scrape',
        status: i === 14 ? 'never' : i === 13 ? 'error' : 'ok',
        count: events.filter(e => e.source === s.id).length,
        last_success_at: i === 14 ? null : new Date(now - (i + 1) * 60000).toISOString(),
        last_run_at: i === 14 ? null : new Date(now - i * 60000).toISOString(),
        error: i === 13 ? 'Source temporarily unavailable; showing previously saved events.' : null
    }));
}
export async function api(path, options = {}) {
    if (!isMock) return getJSON(path, options);
    const u = new URL(path, location.origin);
    const updated_at = new Date(now - 14 * 60000).toISOString();
    if (u.pathname === '/api/stats') return {
        open_now: 24, start_48h: 4, new_this_week: 24,
        total: 24, sources: sourceInfo.length, updated_at
    };
    if (u.pathname === '/api/sources') return sources();
    if (u.pathname === '/api/methodology') return methodology;
    if (u.pathname === '/api/places') {
        const fold=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
        return places.filter(p=>fold(p.name).startsWith(fold(u.searchParams.get('q')||''))).sort((a,b)=>b.population-a.population).slice(0,Number(u.searchParams.get('limit'))||8);
    }
    const mockFilter=(list,params)=>{const cats=(params.get('categories')||'').split(',').filter(Boolean),types=(params.get('types')||'').split(',').filter(Boolean),regs=(params.get('region')||'').split(',').filter(Boolean),codes=(params.get('country')||'').toUpperCase().split(',').filter(Boolean);return list.filter(e=>(!cats.length||cats.some(c=>e.categories.includes(c)))&&types.every(t=>e.flags.includes(t))&&(!regs.length||regs.includes(e.region))&&(!codes.length||codes.includes(e.country_code)));};
    if (u.pathname === '/api/categories') {
        const base=filterEvents(events,{kinds:(u.searchParams.get('kinds')??'hackathon').split(','),days:u.searchParams.get('days')||'all',format:'',q:''});
        return {categories:Object.entries(categoryNames).map(([id,name])=>({id,name,count:base.filter(e=>e.categories.includes(id)).length})).sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name)),types:Object.entries(typeNames).map(([id,name])=>({id,name,count:base.filter(e=>e.flags.includes(id)).length}))};
    }
    if (u.pathname === '/api/regions') {
        const base=filterEvents(events,{kinds:(u.searchParams.get('kinds')??'hackathon').split(','),days:u.searchParams.get('days')||'all',format:u.searchParams.get('format')||'',q:''}),by=new Map();
        for(const e of base)if(e.country_code)by.set(e.country_code,{code:e.country_code,name:e.country_name,region:e.region,count:(by.get(e.country_code)?.count||0)+1});
        return {regions:Object.entries(regionNames).map(([id,name])=>({id,name,count:base.filter(e=>e.region===id).length})),countries:[...by.values()].sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name))};
    }
    if (u.pathname !== '/api/hackathons') throw new Error('Unknown mock API endpoint');
    const state = {
        kinds: (u.searchParams.get('kinds') ?? 'hackathon').split(','),
        days: u.searchParams.get('days') || 'all',
        format: u.searchParams.get('format') || '', q: u.searchParams.get('q') || ''
    };
    let matching=mockFilter(filterEvents(events,state),u.searchParams);
    if(u.searchParams.has('min_score'))matching=matching.filter(e=>e.score!=null&&e.score>=Number(u.searchParams.get('min_score')));
    const nearby=u.searchParams.has('lat')&&u.searchParams.has('lon');
    if(nearby)matching=matching.filter(e=>e.lat!=null&&e.lon!=null&&e.format!=='online').map(e=>({...e,distance_km:distance(Number(u.searchParams.get('lat')),Number(u.searchParams.get('lon')),e.lat,e.lon)})).filter(e=>e.distance_km<=Number(u.searchParams.get('radius_km')||100));
    const sort=u.searchParams.get('sort')||(nearby?'distance':'start');
    let all;
    if(sort==='foryou'){const mine=(u.searchParams.get('interests')||'').split(',').filter(Boolean),pts=e=>(e.score??45)+Math.min(24,12*e.categories.filter(c=>mine.includes(c)).length);all=sortEvents(matching,'start','asc').sort((a,b)=>pts(b)-pts(a));}
    else all=sortEvents(matching,sort,u.searchParams.get('order')||(['score','new'].includes(sort)?'desc':'asc'));
    const page = Math.max(1, Number(u.searchParams.get('page')) || 1);
    const per_page = Math.min(500, Math.max(1, Number(u.searchParams.get('per_page')) || 100));
    return {
        events: all.slice((page - 1) * per_page, page * per_page),
        total: all.length, page, per_page, updated_at, sources: sources()
    };
}
if(isMock){const banner=document.createElement('div');banner.className='mock-banner';banner.textContent='DEMO MODE · SAMPLE EVENTS';document.body.append(banner);}

