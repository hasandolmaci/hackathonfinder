"""Country and region for every event: ISO-3166 alpha-2 code from Event.country, Event.location or the geocoded city.

Pure functions plus a built-in table. The city lookup imports GeoNames lazily, so only the worker/rescore path
ever loads it; the web app only reads COUNTRIES/REGIONS and never imports geonamescache.
"""
from __future__ import annotations

import re
import unicodedata

from .models import Event

REGIONS = {"europe": "Europe", "north_america": "North America", "latin_america": "Latin America", "asia": "Asia",
           "middle_east": "Middle East", "africa": "Africa", "oceania": "Oceania", "online": "Online"}

_TABLE = {
    "europe": "AL:Albania|AD:Andorra|AT:Austria|BY:Belarus|BE:Belgium|BA:Bosnia and Herzegovina|BG:Bulgaria|HR:Croatia|"
              "CY:Cyprus|CZ:Czechia|DK:Denmark|EE:Estonia|FO:Faroe Islands|FI:Finland|FR:France|DE:Germany|GI:Gibraltar|"
              "GR:Greece|GG:Guernsey|HU:Hungary|IS:Iceland|IE:Ireland|IM:Isle of Man|IT:Italy|JE:Jersey|XK:Kosovo|"
              "LV:Latvia|LI:Liechtenstein|LT:Lithuania|LU:Luxembourg|MT:Malta|MD:Moldova|MC:Monaco|ME:Montenegro|"
              "NL:Netherlands|MK:North Macedonia|NO:Norway|PL:Poland|PT:Portugal|RO:Romania|RU:Russia|SM:San Marino|"
              "RS:Serbia|SK:Slovakia|SI:Slovenia|ES:Spain|SE:Sweden|CH:Switzerland|UA:Ukraine|GB:United Kingdom|"
              "VA:Vatican City|AX:Aland Islands|SJ:Svalbard and Jan Mayen",
    "north_america": "US:United States|CA:Canada|BM:Bermuda|GL:Greenland|PM:Saint Pierre and Miquelon",
    "latin_america": "MX:Mexico|BZ:Belize|CR:Costa Rica|SV:El Salvador|GT:Guatemala|HN:Honduras|NI:Nicaragua|PA:Panama|"
                     "AR:Argentina|BO:Bolivia|BR:Brazil|CL:Chile|CO:Colombia|EC:Ecuador|FK:Falkland Islands|GF:French Guiana|"
                     "GY:Guyana|PY:Paraguay|PE:Peru|SR:Suriname|UY:Uruguay|VE:Venezuela|AG:Antigua and Barbuda|AI:Anguilla|"
                     "AW:Aruba|BS:Bahamas|BB:Barbados|BQ:Bonaire|VG:British Virgin Islands|"
                     "KY:Cayman Islands|CU:Cuba|CW:Curacao|DM:Dominica|DO:Dominican Republic|GD:Grenada|GP:Guadeloupe|"
                     "HT:Haiti|JM:Jamaica|MQ:Martinique|MS:Montserrat|PR:Puerto Rico|BL:Saint Barthelemy|"
                     "KN:Saint Kitts and Nevis|LC:Saint Lucia|MF:Saint Martin|VC:Saint Vincent and the Grenadines|"
                     "SX:Sint Maarten|TT:Trinidad and Tobago|TC:Turks and Caicos Islands|VI:US Virgin Islands",
    "asia": "AF:Afghanistan|AM:Armenia|AZ:Azerbaijan|BD:Bangladesh|BT:Bhutan|BN:Brunei|KH:Cambodia|CN:China|GE:Georgia|"
            "HK:Hong Kong|IN:India|ID:Indonesia|JP:Japan|KZ:Kazakhstan|KG:Kyrgyzstan|LA:Laos|MO:Macau|MY:Malaysia|"
            "MV:Maldives|MN:Mongolia|MM:Myanmar|NP:Nepal|KP:North Korea|PK:Pakistan|PH:Philippines|SG:Singapore|"
            "KR:South Korea|LK:Sri Lanka|TW:Taiwan|TJ:Tajikistan|TH:Thailand|TL:Timor-Leste|TM:Turkmenistan|"
            "UZ:Uzbekistan|VN:Vietnam",
    "middle_east": "BH:Bahrain|IR:Iran|IQ:Iraq|IL:Israel|JO:Jordan|KW:Kuwait|LB:Lebanon|OM:Oman|PS:Palestine|QA:Qatar|"
                   "SA:Saudi Arabia|SY:Syria|TR:Turkey|AE:United Arab Emirates|YE:Yemen",
    "africa": "DZ:Algeria|AO:Angola|BJ:Benin|BW:Botswana|BF:Burkina Faso|BI:Burundi|CV:Cabo Verde|CM:Cameroon|"
              "CF:Central African Republic|TD:Chad|KM:Comoros|CG:Congo|CD:DR Congo|CI:Cote d Ivoire|DJ:Djibouti|EG:Egypt|"
              "GQ:Equatorial Guinea|ER:Eritrea|SZ:Eswatini|ET:Ethiopia|GA:Gabon|GM:Gambia|GH:Ghana|GN:Guinea|"
              "GW:Guinea-Bissau|KE:Kenya|LS:Lesotho|LR:Liberia|LY:Libya|MG:Madagascar|MW:Malawi|ML:Mali|MR:Mauritania|"
              "MU:Mauritius|YT:Mayotte|MA:Morocco|MZ:Mozambique|NA:Namibia|NE:Niger|NG:Nigeria|RE:Reunion|RW:Rwanda|"
              "SH:Saint Helena|ST:Sao Tome and Principe|SN:Senegal|SC:Seychelles|SL:Sierra Leone|SO:Somalia|"
              "ZA:South Africa|SS:South Sudan|SD:Sudan|TZ:Tanzania|TG:Togo|TN:Tunisia|UG:Uganda|EH:Western Sahara|"
              "ZM:Zambia|ZW:Zimbabwe",
    "oceania": "AS:American Samoa|AU:Australia|CK:Cook Islands|FJ:Fiji|PF:French Polynesia|GU:Guam|KI:Kiribati|"
               "MH:Marshall Islands|FM:Micronesia|NR:Nauru|NC:New Caledonia|NZ:New Zealand|NU:Niue|NF:Norfolk Island|"
               "MP:Northern Mariana Islands|PW:Palau|PG:Papua New Guinea|WS:Samoa|SB:Solomon Islands|TK:Tokelau|"
               "TO:Tonga|TV:Tuvalu|VU:Vanuatu|WF:Wallis and Futuna",
}
COUNTRIES = {code: (name, region) for region, text in _TABLE.items()
             for code, name in (item.split(":", 1) for item in text.split("|"))}

# Alternative spellings and local names -> ISO2 (lowercase, accents stripped).
_ALIASES = {
    "usa": "US", "u.s.a.": "US", "u.s.": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "great britain": "GB", "britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB", "nederland": "NL", "the netherlands": "NL", "holland": "NL",
    "deutschland": "DE", "osterreich": "AT", "schweiz": "CH", "suisse": "CH", "svizzera": "CH", "belgie": "BE",
    "belgique": "BE", "espana": "ES", "italia": "IT", "turkiye": "TR", "polska": "PL", "sverige": "SE",
    "norge": "NO", "danmark": "DK", "suomi": "FI", "ellada": "GR", "magyarorszag": "HU", "czech republic": "CZ",
    "slovensko": "SK", "hrvatska": "HR", "srbija": "RS", "russian federation": "RU", "ukraina": "UA",
    "brasil": "BR", "mejico": "MX", "uae": "AE", "u.a.e.": "AE", "emirates": "AE", "ksa": "SA", "korea": "KR",
    "republic of korea": "KR", "korea, republic of": "KR", "hongkong": "HK", "hong kong sar": "HK",
    "viet nam": "VN", "burma": "MM", "macedonia": "MK", "swaziland": "SZ", "ivory coast": "CI",
    "cape verde": "CV", "east timor": "TL", "democratic republic of the congo": "CD", "drc": "CD",
    "republic of the congo": "CG", "palestinian territory": "PS", "state of palestine": "PS",
    "peoples republic of china": "CN", "prc": "CN", "bosnia": "BA", "eire": "IE", "the gambia": "GM",
    "u.s. virgin islands": "VI", "czech": "CZ", "cote d'ivoire": "CI",
}
_US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
              "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
              "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"}
_ONLINE = {"online", "virtual", "remote", "worldwide", "global", "internet", "everywhere"}
_SPLIT = re.compile(r"[,;|/()]")
_NAMES: dict[str, str] = {}


def _norm(value: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))
    return " ".join(text.replace("’", "'").split())


def _names() -> dict[str, str]:
    if not _NAMES:
        for code, (name, _region) in COUNTRIES.items():
            _NAMES[_norm(name)] = code
            _NAMES[code.lower()] = code
        _NAMES.update(_ALIASES)
    return _NAMES


def country_code(text: str | None) -> str | None:
    """ISO2 code for a country name, local name or code ("nl", "USA", "UK"), else None."""
    return _names().get(_norm(text or "").strip(" .")) if text else None


def _from_location(location: str | None) -> str | None:
    """Last comma part naming a country; a trailing bare US state code ("Austin, TX") means the US."""
    parts = [p.strip() for p in _SPLIT.split(location or "") if p.strip()]
    for i in range(len(parts) - 1, -1, -1):
        if i > 0 and parts[i] in _US_STATES and i == len(parts) - 1:
            return "US"
        found = country_code(parts[i])
        if found:
            return found
    return None


def _from_city(location: str | None, hint: str | None) -> str | None:
    """Country of the best-known GeoNames city in the location (worker/rescore path only)."""
    from . import geo
    city = geo.match(location, hint)
    return city["country_code"] if city else None


def resolve(event: Event, use_geo: bool = True, geo_code: str | None = None) -> tuple[str | None, str | None]:
    """(country_code, region). Online events are (None, "online"); unknown places are (None, None).
    geo_code is the country a geocoder learned for the event; it ranks after the event's own country and location."""
    if event.format == "online" or (event.location and _norm(event.location) in _ONLINE):
        return None, "online"
    code = country_code(event.country) or _from_location(event.location) or geo_code
    if not code and use_geo and event.location:
        try:
            code = _from_city(event.location, None)
        except ImportError:
            code = None
    return (code, COUNTRIES[code][1]) if code in COUNTRIES else (None, None)


def country_name(code: str | None) -> str | None:
    return COUNTRIES[code][0] if code in COUNTRIES else None
