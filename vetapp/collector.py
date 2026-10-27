"""Bounded, robots-aware collection of public link metadata. Never fetch forum posts."""
import asyncio
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .db import db, now, rows

USER_AGENT = 'StadoVetResearch/1.0 (+public veterinary link monitoring; no login)'
SOURCES = [
    {'id': 'giw', 'name': 'Główny Inspektorat Weterynarii', 'kind': 'official',
     'url': 'https://www.wetgiw.gov.pl/main/komunikaty'},
    {'id': 'agrofoto', 'name': 'Agrofoto · forum hodowców', 'kind': 'forum',
     'url': 'https://www.agrofoto.pl/forum/'},
    {'id': 'farmer', 'name': 'Farmer · bydło i mleko', 'kind': 'media',
     'url': 'https://www.farmer.pl/produkcja-zwierzeca/bydlo-i-mleko/'},
]
ALLOWED_HOSTS = {urlsplit(s['url']).hostname for s in SOURCES}
REGIONS = {
    'pomorskie': ['pomorsk', 'gdansk', 'slupsk', 'tczew', 'kartuz', 'koscierz', 'chojnic', 'wejherow', 'bytow', 'malbork'],
    'warmińsko-mazurskie': ['warmin', 'mazursk', 'olsztyn', 'ostrod', 'elblag', 'gizyck', 'mragow', 'szczytn', 'bartoszyc', 'ilaw', 'ketrzyn', 'oleck', 'goldap'],
    'podlaskie': ['podlask', 'bialyst', 'lomz', 'suwalk', 'augustow', 'grajew', 'monieck', 'monki', 'sokolsk', 'zambrow', 'wysokomazow'],
}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower().replace('ł', 'l')) if not unicodedata.combining(c))


def classify(title):
    t = normalized(title)
    if any(w in t for w in ['mastitis', 'wymie', 'wymion', 'mleka', 'mleko', 'komork']):
        return 'wymię i mleko'
    if any(w in t for w in ['wyciel', 'porod', 'rozrod', 'plodn', 'zaciel']):
        return 'rozród'
    if any(w in t for w in ['pasz', 'zywien', 'kwasic', 'ketoz']):
        return 'żywienie'
    if any(w in t for w in ['pryszczyc', 'bvd', 'ibr', 'guzowat', 'niebiesk', 'zakaz', 'chorob', 'epidem']):
        return 'choroby zakaźne'
    return 'inne'


def relevant(title):
    t = normalized(title)
    return any(w in t for w in ['bydl', 'krow', 'ciel', 'mastitis', 'pryszczyc', 'bvd', 'ibr', 'niebieskiego jezyka', 'guzowat', 'wymion', 'ketoz'])


def regions_for(title):
    t = normalized(title)
    # County/city mentions are clues, not verified outbreak locations.
    return [name for name, terms in REGIONS.items() if any(re.search(r'(?<![a-z])' + re.escape(term), t) for term in terms)] or ['ogólnopolskie / nieustalone']


def clean_title(text):
    text = re.sub(r'\S+@\S+\.\S+', '[e-mail usunięty]', text)
    text = re.sub(r'(?<!\w)(?:\+48[ -]?)?(?:\d[ -]?){9}(?!\w)', '[numer usunięty]', text)
    return re.sub(r'\s+', ' ', text).strip()[:300]


def parse_links(html, source):
    soup = BeautifulSoup(html, 'html.parser')
    for unwanted in soup.select('nav, header, footer, script, style'):
        unwanted.decompose()
    found = {}
    for a in soup.select('a[href]'):
        title = clean_title(a.get_text(' ', strip=True))
        url = urljoin(source['url'], a['href'])
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != urlsplit(source['url']).hostname:
            continue
        if not 15 <= len(title) <= 300 or not relevant(title):
            continue
        if any(x in parts.path.lower() for x in ['/profile/', '/login', '/register', '/tag/', '/search', '/page/']):
            continue
        if source['kind'] == 'forum' and '/topic/' not in parts.path:
            continue
        if parts.path.rstrip('/') == urlsplit(source['url']).path.rstrip('/'):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        if url in found:
            continue
        region_list = regions_for(title)
        found[url] = {
            'title': title, 'source_url': url, 'source_name': source['name'],
            'source_kind': source['kind'], 'category': classify(title),
            'region': ', '.join(region_list),
            'summary': 'Publiczny tytuł i odnośnik. Treść zgłoszenia wymaga oceny lekarza. '
                       + ('Region rozpoznano wyłącznie po wzmiance w tytule.' if region_list[0] != 'ogólnopolskie / nieustalone'
                          else 'Brak wskazania jednego z trzech województw w tytule; kontekst ogólny.'),
        }
        if len(found) >= 40:
            break
    return list(found.values())


async def bounded_get(client, url):
    for _ in range(4):
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in ALLOWED_HOSTS:
            raise ValueError('Przekierowanie poza dozwolone źródła')
        async with client.stream('GET', url) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers['location'])
                continue
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ValueError('Źródło przekroczyło limit rozmiaru')
            return r.status_code, bytes(body).decode('utf-8', errors='replace')
    raise ValueError('Zbyt wiele przekierowań')


async def collect_source(client, source):
    try:
        parts = urlsplit(source['url'])
        status, body = await bounded_get(client, f'{parts.scheme}://{parts.netloc}/robots.txt')
        if status == 200:
            robots = RobotFileParser()
            robots.parse(body.splitlines())
            if not robots.can_fetch(USER_AGENT, source['url']):
                return record(source, 'blocked', 0, 'robots.txt nie zezwala na pobranie tej strony.')
            delay = max(robots.crawl_delay(USER_AGENT) or 0, robots.crawl_delay('*') or 0, 1)
            if delay > 30:
                return record(source, 'blocked', 0, 'Źródło wymaga dłuższego odstępu; pominięto automatyczny odczyt.')
            await asyncio.sleep(delay)
        elif status != 404:
            return record(source, 'blocked', 0, f'Nie można zweryfikować robots.txt (HTTP {status}).')
        status, html = await bounded_get(client, source['url'])
        if status != 200:
            return record(source, 'error', 0, f'Źródło zwróciło HTTP {status}; bez obchodzenia ograniczeń.')
        items = parse_links(html, source)
        added = 0
        with db() as c:
            for item in items:
                fields = list(item)
                cur = c.execute(f"INSERT OR IGNORE INTO reports ({','.join(fields)},observed_at) VALUES ({','.join('?' for _ in fields)},?)",
                                (*item.values(), now()))
                added += cur.rowcount
        return record(source, 'ok', added, f'Odczytano {len(items)} pasujących tytułów; dodano {added}. Bez pobierania treści postów.')
    except (httpx.HTTPError, ValueError, KeyError):
        return record(source, 'error', 0, 'Brak dostępu do źródła. Sprawdź dozwolone domeny i dostępność portalu.')


def record(source, status, added, detail):
    with db() as c:
        c.execute('INSERT INTO collection_runs(source_id,status,added,detail,created_at) VALUES(?,?,?,?,?)',
                  (source['id'], status, added, detail, now()))
    return {'source_id': source['id'], 'status': status, 'added': added, 'detail': detail}


lock = asyncio.Lock()


async def collect_all():
    async with lock:
        with db() as c:
            recent = c.execute('SELECT created_at FROM collection_runs ORDER BY id DESC LIMIT 1').fetchone()
        if recent:
            from datetime import datetime, timezone
            if (datetime.now(timezone.utc) - datetime.fromisoformat(recent['created_at'])).total_seconds() < 900:
                return {'throttled': True, 'message': 'Źródła sprawdzano niedawno. Odświeżenie jest dostępne co 15 minut.', 'results': []}
        async with httpx.AsyncClient(timeout=15, headers={'User-Agent': USER_AGENT}, follow_redirects=False) as client:
            results = []
            for source in SOURCES:
                results.append(await collect_source(client, source))
        return {'throttled': False, 'results': results}


def source_status():
    with db() as c:
        return [{**s, 'last_run': next(iter(rows(c, 'SELECT * FROM collection_runs WHERE source_id=? ORDER BY id DESC LIMIT 1', (s['id'],))), None)} for s in SOURCES]


async def scheduler():
    while True:
        delay = 6 * 3600
        try:
            result = await collect_all()
            if result.get('throttled'):
                delay = 15 * 60
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Błąd harmonogramu zbierania źródeł')
        await asyncio.sleep(delay)
