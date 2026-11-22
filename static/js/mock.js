import {sourceInfo,filterEvents,sortEvents,getJSON} from './shared.js';
export const isMock = new URLSearchParams(location.search).get('mock')==='1';
const titles=['Open Source Weekend','Agents for Good','Build the Next Internet','Climate Code Collective','Midnight Makers','Future of Finance','The Local AI Hack','Campus Builders','Creative Machines','Hack the Everyday','Better Cities Buildathon','Zero to One Weekend','Small Tools, Big Ideas','HealthTech Hack','The Open Data Challenge','Reimagine Learning','Build Without Borders','Weekend on the Web','The Accessibility Sprint','Green Grid Hack','AI Studio Weekend','Hardware & Humans','The Community Build','Next Chapter Hack','Pixel Planet Jam','One Button Game Jam','Cozy Worlds Jam','Tiny Adventure Jam','Signal Capture CTF','Midnight Security CTF','Flag Hunters CTF','Codebreakers CTF','Forecast the Future','Data for Nature','Algorithm Arena','Vision Challenge','Ideas for Tomorrow','Future Cities Ideathon','Circular Economy Pitch','Moonshot Ideas'];
const now=Date.now(), hour=36e5;
const events=titles.map((title,i)=>{const kind=i<24?'hackathon':i<28?'game_jam':i<32?'ctf':i<36?'coding_competition':'ideathon';const source=i<24?sourceInfo[i%10]:sourceInfo[kind==='game_jam'?12:kind==='ctf'?11:kind==='coding_competition'?10:3];const offset=i<7?i*13+1:i<24?(i-6)*30:(i-24)*17+3;const format=['online','in-person','online','hybrid'][i%4];return {source:source.id,source_id:String(i),url:`https://${source.host}/sample-event-${i+1}`,title,description:`A sample ${kind.replaceAll('_',' ')} for curious builders.`,start:i===23?null:new Date(now+(i===0?-24:offset)*hour).toISOString(),end:new Date(now+(offset+72)*hour).toISOString(),format,location:format==='online'?null:['Berlin, Germany','London, UK','San Francisco, US','Bengaluru, India'][i%4],prize:i%6===0?null:`$${((i%8+1)*2500).toLocaleString('en-US')}`,prize_usd:i%6===0?null:(i%8+1)*2500,participants:i%7===0?null:48+i*37,kind,also_on:i%5===0?['luma','meetup']:[],tags:i%2?['ai','open-source']:['climate','student'],fetched_at:new Date(now-i*hour).toISOString()};});
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
    if (u.pathname !== '/api/hackathons') throw new Error('Unknown mock API endpoint');
    const state = {
        kinds: (u.searchParams.get('kinds') ?? 'hackathon').split(','),
        days: u.searchParams.get('days') || 'all',
        format: u.searchParams.get('format') || '', q: u.searchParams.get('q') || ''
    };
    const all = sortEvents(filterEvents(events, state),
        u.searchParams.get('sort') || 'start', u.searchParams.get('order') || 'asc');
    const page = Math.max(1, Number(u.searchParams.get('page')) || 1);
    const per_page = Math.min(500, Math.max(1, Number(u.searchParams.get('per_page')) || 100));
    return {
        events: all.slice((page - 1) * per_page, page * per_page),
        total: all.length, page, per_page, updated_at, sources: sources()
    };
}
if(isMock){const banner=document.createElement('div');banner.className='mock-banner';banner.textContent='DEMO MODE · SAMPLE EVENTS';document.body.append(banner);}

