"""Topic categories and type flags for every event.

Pure functions over an Event: no I/O, no database. Categories come from keyword rules with word
boundaries over title/tags/themes ("head"), the short description, and the long signals.text,
plus a few source hints. Flags are yes/no facts (student, beginner, cash_prize, travel, weekend).
"new" is not stored: it depends on today's date, so the API computes it from first_seen.
"""
from __future__ import annotations

from datetime import timedelta
import re

from .models import Event

CATEGORIES = {
    "ai": "AI & ML", "web3": "Web3 & Crypto", "fintech": "Fintech", "health": "Health & Biotech",
    "climate": "Climate & Sustainability", "gaming": "Gaming", "education": "Education",
    "social": "Social Impact", "security": "Cybersecurity", "hardware": "Hardware & IoT",
    "robotics": "Robotics", "xr": "AR/VR", "opensource": "Open Source", "data": "Data Science",
    "mobile": "Mobile", "cloud": "Cloud & DevOps", "devtools": "Developer Tools", "web": "Web Dev",
    "design": "Design & UX", "space": "Space Tech",
}
TYPES = {"student": "Student", "beginner": "Beginner friendly", "cash_prize": "Cash prizes",
         "travel": "Travel support", "weekend": "Weekend", "new": "New this week"}
NEW_DAYS = 7
MAX_CATEGORIES = 4

# id -> (strong keywords, weak keywords). Strong words are unambiguous; weak words ("game", "data",
# "space") only count when they appear in the title/tags/themes or repeatedly in the description.
RULES = {
    "ai": (r"ai|gen ?ai|artificial intelligence|machine learning|deep learning|llms?|gpt|chat ?gpt|openai|anthropic|"
           r"claude|generative|agentic|ai agents?|neural|nlp|computer vision|vibe[- ]?cod(?:e|ing)|mcp|ml|mistral|"
           r"hugging ?face|codex|copilot|prompt(?:ing| engineering)|rag|machine learning/ai",
           r"agents?|intelligence"),
    "web3": (r"web ?3|blockchain|crypto(?:currency|currencies)?|ethereum|eth|solana|bitcoin|defi|nfts?|daos?|"
             r"smart contracts?|on-?chain|polygon|arbitrum|starknet|aptos|cardano|polkadot|chainlink|"
             r"zero[- ]knowledge|zk|rollups?|layer ?2|ethglobal|stablecoins?|tokenization|dapps?|base chain|"
             r"filecoin|cosmos|near protocol|avalanche|monad|web3",
             r"tokens?|sui|stellar|decentrali[sz]ed"),
    "fintech": (r"fintech|finance|financial|banking|banks?|payments?|insurtech|insurance|trading|stock market|lending|"
                r"neobank|wealth|upi|investing|investments?|accounting|credit|fraud",
                r"money|economy|economic"),
    "health": (r"health|health ?care|health ?tech|medical|medicine|biotech|bioinformatics|biology|clinical|pharma|"
               r"genomics|wellness|mental health|diagnos(?:is|tics?)|patients?|hospitals?|life sciences|medtech|"
               r"biomedical|neuroscience|longevity|cancer|diseases?|diabetes|covid(?:-19)?|pandemic|drug discovery|telemedicine|mhealth",
               r"bio|care"),
    "climate": (r"climate|sustainab(?:le|ility)|clean ?tech|renewables?|carbon|energy|environment(?:al)?|ecolog(?:y|ical)|"
                r"recycling|agri ?tech|agriculture|farming|biodiversity|net[- ]zero|solar|greentech|conservation|"
                r"wildlife|clean energy|cleantech|waste|farms?|farmers?|agri|agricultural",
                r"green|water|ocean|nature|earth|food"),
    "gaming": (r"gam(?:ing|edev)|game ?dev(?:elopment)?|game (?:jam|design|development|engine)|video ?games?|esports?|"
               r"unity|unreal(?: engine)?|godot|roblox|minecraft|itch\.io|ludum dare|indie games?|pygame",
               r"games?|play|puzzle"),
    "education": (r"education(?:al)?|ed ?tech|e-?learning|teachers?|teaching|classroom|curriculum|tutoring|literacy|"
                  r"students? learning|learning platform",
                  r"(?<!machine )(?<!deep )learning|school"),
    "social": (r"social good|social impact|non-?profits?|civic(?:s| tech)?|civictech|govtech|gov ?tech|humanitarian|"
               r"accessibility|accessible|sdgs?|charity|disaster|poverty|tech for good|public good|for good|"
               r"social innovation|sustainable development|refugees?|inclusion|public sector|social entrepreneurship",
               r"social|community|government|gov|women|diversity|society|impact"),
    "security": (r"cyber ?security|cyber|security|infosec|ctf|capture the flag|pentest(?:ing)?|penetration test(?:ing)?|"
                 r"vulnerabilit(?:y|ies)|malware|red team|forensics|exploits?|privacy|encryption|cryptography|"
                 r"zero trust|appsec|devsecops|blue team|reverse engineering",
                 r"safe|safety|trust"),
    "hardware": (r"hardware|iot|internet of things|embedded|arduino|raspberry pi|esp32|fpga|sensors?|wearables?|pcb|"
                 r"electronics?|microcontrollers?|makeathon|maker(?:s|space)?|3d print(?:ing)?|firmware|smart home|"
                 r"edge computing|semiconductors?|chip design",
                 r"devices?|physical"),
    "robotics": (r"robot(?:s|ics?)?(?! process)|drones?|autonomous|self-driving|uavs?|ros|mechatronics|humanoids?",
                 r"vehicles?"),
    "xr": (r"ar ?/ ?vr|ar ?& ?vr|vr|xr|augmented reality|virtual reality|mixed reality|metaverse|spatial computing|"
           r"vision pro|hololens|webxr|immersive|oculus|meta quest",
           r"3d"),
    "opensource": (r"open[- ]?source|foss|oss|hacktoberfest|gsoc|google summer of code|linux|open source software",
                   r"github|contribut(?:e|ors?|ions?)|opensource"),
    "data": (r"data science|data analytics?|analytics|big data|data engineering|datasets?|datathon|data visuali[sz]ation|"
             r"databases?|data-driven|business intelligence|data mining|data viz|statistics|statistical|"
             r"data analysis|predictive modell?ing|kaggle",
             r"data|insights|visuali[sz]ation"),
    "mobile": (r"mobile|android|ios|iphone|ipad|flutter|react native|swiftui|kotlin|app store|play store|"
               r"mobile apps?|apple watch|harmonyos",
               r"swift"),
    "cloud": (r"cloud|devops|aws|amazon web services|azure|gcp|google cloud|kubernetes|k8s|docker|serverless|sre|"
              r"ci/cd|terraform|cloudflare|microservices|observability|platform engineering|mlops|digitalocean|"
              r"data ?center|oracle cloud",
              r"infrastructure|infra|deploy(?:ment)?|hosting"),
    "devtools": (r"developer tools?|dev ?tools?|developer experience|dx|sdks?|clis?|low[- ]?code|no[- ]?code|"
                 r"developer productivity|productivity|ides?|plugins?|browser extensions?|dev ?ops tools?|"
                 r"atlassian|codegeist|forge|vs ?code|developer platform|apis?|jetbrains|notion|zapier",
                 r"automation|workflow|saas|enterprise|tools?|extension|software"),
    "web": (r"web(?! ?3)|web ?dev(?:elopment)?|web (?:apps?|applications?|design|development|platform)|websites?|"
            r"front-?end|back-?end|full[- ]?stack|react|next\.?js|javascript|typescript|html|css|node\.?js|"
            r"vue|svelte|django|flask|ruby on rails|php|wordpress|web ?assembly|wasm|progressive web apps?|"
            r"software development",
            r"browser"),
    "design": (r"design|ux|ui|ui ?/ ?ux|user experience|user interface|figma|graphic(?:s| design)|branding|"
               r"typography|illustration|animation|product design|creative coding|generative art|interaction design",
               r"creative|art|music|visual|prototype|fashion|film|media"),
    "space": (r"space ?tech|nasa|satellites?|astronomy|aerospace|rockets?|orbital|orbit|spacex|esa|space apps|"
              r"astrophysics|cubesat|space exploration|astronauts?|lunar|mars|space station|geospatial|earth observation",
              r"space|moon|galactic|astro|stars?"),
}

SOURCE_HINTS = {"ethglobal": "web3", "dorahacks": "web3", "hackquest": "web3", "kaggle": "data", "zindi": "data"}
KIND_HINTS = {"game_jam": "gaming", "ctf": "security"}

_BOUNDARY = (r"(?<![a-z0-9])(?:", r")(?![a-z0-9])")
_GAME_IDIOM = r"(?![- ]chang)(?![- ]plan)(?![- ]over)(?![- ]on(?![a-z]))(?![- ]day)(?! of thrones)"


def _compile(words: str) -> re.Pattern:
    return re.compile(_BOUNDARY[0] + words + _BOUNDARY[1], re.I)


_COMPILED: dict[str, tuple[re.Pattern, re.Pattern]] = {}
for _id, (_strong, _weak) in RULES.items():
    if _id == "gaming":  # "game changer", "game plan" are idioms, not video games
        _weak = r"games?" + _GAME_IDIOM
    _COMPILED[_id] = (_compile(_strong), _compile(_weak))


def _head(event: Event) -> str:
    themes = event.signals.get("themes")
    themes = themes if isinstance(themes, list) else []
    return " ".join([event.title, *event.tags, *(str(t) for t in themes)])


def _text(event: Event) -> str:
    return str(event.signals.get("text") or "")[:3000]


def category_scores(event: Event) -> dict[str, int]:
    """Evidence points per category id (only ids with any evidence). Head hits weigh most."""
    head, desc, text = _head(event), event.description or "", _text(event)
    scores = {}
    for cid, (strong, weak) in _COMPILED.items():
        points = 0
        n = len(strong.findall(head))
        points += (3 + (n > 1)) if n else 0
        points += 2 if weak.search(head) else 0
        points += 2 if strong.search(event.title) else 0  # the title is the clearest statement of topic
        n = len(strong.findall(desc))
        points += (2 + (n > 1)) if n else 0
        points += min(len(weak.findall(desc)), 2)
        points += min(len(strong.findall(text)), 3)
        if points:
            scores[cid] = points
    return scores


def categorize(event: Event) -> list[str]:
    """Return 0-4 category ids, best first (taxonomy order breaks ties)."""
    scores = {cid: pts for cid, pts in category_scores(event).items() if pts >= 2}
    hint = SOURCE_HINTS.get(event.source) or KIND_HINTS.get(event.kind)
    if hint:
        scores[hint] = max(scores.get(hint, 0), 6)
    if not scores:
        return []
    order = list(CATEGORIES)
    ranked = sorted(scores, key=lambda cid: (-scores[cid], order.index(cid)))
    floor = max(2, scores[ranked[0]] / 2)
    return [cid for cid in ranked if scores[cid] >= floor][:MAX_CATEGORIES]


_STUDENT = re.compile(
    r"(?<![a-z0-9])(?:students? only|for (?:college |university |high school |undergraduate |all )?students|"
    r"calling all students|student hackathon|student[- ]led|(?:university|college|campus|collegiate|high[- ]school|"
    r"school) hack(?:athon|s)?|(?:university|college|high school|undergraduate) students|currently enrolled|"
    r"students?(?:'|’)? (?:hackathon|competition))(?![a-z0-9])", re.I)
_STUDENT_HEAD = re.compile(r"(?<![a-z0-9])(?:students?|collegiate|high[- ]school|university|college|campus)(?![a-z0-9])", re.I)
_BEGINNER = re.compile(
    r"(?<![a-z0-9])(?:beginners?|first[- ]time(?:rs?| hackers?)?|newbies?|novices?|"
    r"no (?:prior |previous )?(?:coding |programming |hackathon )?experience|never (?:coded|hacked|done a hackathon)|"
    r"all (?:skill )?levels|all experience levels|first hackathon)(?![a-z0-9])", re.I)
_NOT_BEGINNER = {"not", "non", "no", "advanced", "isn't", "n't"}


def _beginner_text(text: str) -> bool:
    for m in _BEGINNER.finditer(text):
        before = re.findall(r"[\w']+", text[:m.start()].casefold())[-2:]
        if m[0].casefold().startswith("beginner") and set(before) & _NOT_BEGINNER:
            continue
        return True
    return False


def flags(event: Event) -> list[str]:
    """Return the stored yes/no flags (no "new") in a fixed order."""
    from .score import extract
    head, desc, text = _head(event), event.description or "", _text(event)
    body = f"{desc} {text}"
    signals = event.signals
    found = []
    if (signals.get("students_only") or event.source in {"mlh", "hackclub"} or "student" in {t.casefold() for t in event.tags}
            or _STUDENT_HEAD.search(event.title) or _STUDENT.search(body)):
        found.append("student")
    if _beginner_text(f"{head} {body}"):
        found.append("beginner")
    amount = signals.get("prize_amount")
    if (event.prize_usd or 0) > 0 or (isinstance(amount, (int, float)) and amount > 0 and not signals.get("prize_noncash")):
        found.append("cash_prize")
    if extract(event).get("travel_support"):
        found.append("travel")
    if (event.format in {"in-person", "hybrid"} and event.start is not None and event.start.weekday() >= 4
            and (event.end is None or event.end - event.start <= timedelta(days=3))):
        found.append("weekend")
    return found


def pack(values: list[str]) -> str:
    """Comma-wrapped text for SQL filtering: ['ai', 'web3'] -> ',ai,web3,'; [] -> ','."""
    return "," + "".join(v + "," for v in values) if values else ","


def unpack(text: str | None) -> list[str]:
    return [v for v in (text or "").split(",") if v]
