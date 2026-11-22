# Dutch hackathon sources (checked 2026-11-22)

Added
- netherlandshackathons.com: Astro site, robots allow all except /go/ and /api/. rss.xml (10 current events) + sitemap.xml
  (events incl. past) -> /events/<slug> pages with schema.org Event JSON-LD (dates, address, price, original Luma/Eventbrite URL in offers[0].url).
  Collector `netherlandshackathons`, pass "quick". Live: 9 upcoming (the 10th, CRCL, ended today).
  The same operator runs sibling country sites (ukhackathons.com, germanhackathons.com, ...) with the same structure; not added (out of scope).

Skipped
- aanmelder.nl: search URL 404s; no stable public listing found.
- hackathon.nl, dutchtechweek.com: unreachable (connection failed) from this machine.
- techleap.nl/events: reachable, no hackathon entries on the page.
- hackyourfuture.net/events, tue.nl events: 404; university calendars have no recurring hackathon listing and need per-site parsing.
- Devpost API with search=netherlands/amsterdam: 0 results (Devpost is already collected globally).
- Not checked (no time): StartupAmsterdam, GovTech NL pages (its hackathon already appears via Eventbrite/NH), YES!Delft, B. Amsterdam, Brainport.

Existing sources
- Eventbrite: /d/netherlands--<city>/hackathon/ returns HTTP 200 for every Dutch slug, but small cities have no page of their own and
  fall back to a country-wide ranking (even an invalid slug redirects to /d/netherlands/). Added "netherlands" + 14 cities; each ranks differently.
- Meetup: nl--<City> verified for 14 cities by the page heading "events near <city>, NL" (Utrecht, The Hague/Den Haag, Delft, Leiden, Groningen,
  Nijmegen, Enschede, Maastricht, Tilburg, Breda, Haarlem, Arnhem, Amersfoort, 's-Hertogenbosch). Rotterdam/Eindhoven/Amsterdam already existed.
- Luma: city queries added (Nijmegen, Enschede, Maastricht, Tilburg, Breda, Haarlem, Arnhem, Amersfoort, Den Haag, Den Bosch, 's-Hertogenbosch);
  _in_city accepts aliases (The Hague = Den Haag = 's-Gravenhage, 's-Hertogenbosch = Den Bosch).
