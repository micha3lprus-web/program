import asyncio
import csv
import io
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import agent, collector
from .db import db, init_db, now, rows, audit
from .models import Animal, Chat, Farm, Report, Review, Treatment, Visit

STATIC = Path(__file__).parent / 'static'


@asynccontextmanager
async def lifespan(app):
    init_db()
    task = asyncio.create_task(collector.scheduler()) if os.environ.get('VET_AUTO_COLLECT') == '1' else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title='StadoVet', version='0.1.0', lifespan=lifespan)


@app.middleware('http')
async def same_origin(request: Request, call_next):
    # Local single-user application: reject cross-site mutation and DNS rebinding.
    host = request.url.hostname
    configured = os.environ.get('VET_ALLOWED_HOST', '')
    if host not in {'localhost', '127.0.0.1', '::1', 'testserver', configured}:
        return JSONResponse({'detail': 'Niedozwolony host. Ta wersja jest przeznaczona do pracy lokalnej.'}, status_code=403)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
            return JSONResponse({'detail': 'Żądanie z innej witryny jest niedozwolone.'}, status_code=403)
        size = request.headers.get('content-length')
        if size and int(size) > 50_000:
            return JSONResponse({'detail': 'Zbyt duże żądanie.'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail': 'Taki numer kolczyka lub odnośnik już istnieje albo powiązany rekord nie istnieje.'}, status_code=409)


def ensure(c, table, entity_id):
    row = c.execute(f'SELECT * FROM {table} WHERE id=?', (entity_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Nie znaleziono rekordu')
    return dict(row)


def save(c, table, values):
    columns = ','.join(values)
    marks = ','.join('?' for _ in values)
    cur = c.execute(f'INSERT INTO {table} ({columns},created_at) VALUES ({marks},?)', (*values.values(), now()))
    audit(c, 'create', table, cur.lastrowid)
    return ensure(c, table, cur.lastrowid)


@app.get('/api/health')
def health():
    with db() as c:
        c.execute('SELECT 1')
    return {'status': 'ok', 'version': '0.1.0'}


@app.get('/api/overview')
def overview():
    result = agent.read_records()
    with db() as c:
        result['regions'] = rows(c, 'SELECT f.region,count(DISTINCT f.id) farms,count(a.id) animals FROM farms f LEFT JOIN animals a ON a.farm_id=f.id GROUP BY f.region')
        result['demo'] = bool(c.execute('SELECT count(*) FROM farms WHERE is_demo=1').fetchone()[0])
        result['signals'] = c.execute("SELECT count(*) FROM reports WHERE verification='unverified'").fetchone()[0]
        result['visits'] = agent.read_records('visits')[:5]
    return result


@app.get('/api/farms')
def farms():
    with db() as c:
        return rows(c, 'SELECT f.*,count(a.id) animal_count FROM farms f LEFT JOIN animals a ON a.farm_id=f.id GROUP BY f.id ORDER BY f.name')


@app.post('/api/farms', status_code=201)
def add_farm(item: Farm):
    with db() as c:
        return save(c, 'farms', item.model_dump())


@app.put('/api/farms/{entity_id}')
def update_farm(entity_id: int, item: Farm):
    with db() as c:
        ensure(c, 'farms', entity_id)
        values = item.model_dump()
        c.execute('UPDATE farms SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), entity_id))
        audit(c, 'update', 'farms', entity_id)
        return ensure(c, 'farms', entity_id)


@app.get('/api/animals')
def animals():
    with db() as c:
        return rows(c, '''SELECT a.*,f.name farm_name,f.region,f.is_demo,
            (SELECT max(milk_until) FROM treatments t WHERE t.animal_id=a.id) milk_until,
            (SELECT max(meat_until) FROM treatments t WHERE t.animal_id=a.id) meat_until
            FROM animals a JOIN farms f ON f.id=a.farm_id ORDER BY a.id DESC''')


@app.post('/api/animals', status_code=201)
def add_animal(item: Animal):
    with db() as c:
        ensure(c, 'farms', item.farm_id)
        return save(c, 'animals', item.model_dump(mode='json'))


@app.get('/api/animals/{entity_id}')
def animal_detail(entity_id: int):
    with db() as c:
        animal = ensure(c, 'animals', entity_id)
        animal['farm'] = ensure(c, 'farms', animal['farm_id'])
        animal['treatments'] = rows(c, 'SELECT * FROM treatments WHERE animal_id=? ORDER BY treated_at DESC', (entity_id,))
        animal['visits'] = rows(c, 'SELECT * FROM visits WHERE animal_id=? ORDER BY scheduled_at DESC', (entity_id,))
        return animal


@app.put('/api/animals/{entity_id}')
def update_animal(entity_id: int, item: Animal):
    with db() as c:
        old = ensure(c, 'animals', entity_id)
        if old['farm_id'] != item.farm_id:
            raise HTTPException(422, 'Przeniesienie zwierzęcia wymaga osobnego rejestru przemieszczeń; gospodarstwo jest niezmienne.')
        values = item.model_dump(mode='json')
        c.execute('UPDATE animals SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), entity_id))
        audit(c, 'update', 'animals', entity_id)
        return ensure(c, 'animals', entity_id)


@app.get('/api/visits')
def visits():
    with db() as c:
        return rows(c, 'SELECT v.*,f.name farm_name,f.region,f.is_demo,a.ear_tag FROM visits v JOIN farms f ON f.id=v.farm_id LEFT JOIN animals a ON a.id=v.animal_id ORDER BY v.scheduled_at')


def validate_visit(c, item):
    ensure(c, 'farms', item.farm_id)
    if item.animal_id and ensure(c, 'animals', item.animal_id)['farm_id'] != item.farm_id:
        raise HTTPException(422, 'Zwierzę nie należy do wybranego gospodarstwa')
    values = item.model_dump(mode='json')
    values['scheduled_at'] = item.scheduled_at.astimezone(timezone.utc).isoformat(timespec='seconds')
    return values


@app.post('/api/visits', status_code=201)
def add_visit(item: Visit):
    with db() as c:
        return save(c, 'visits', validate_visit(c, item))


@app.put('/api/visits/{entity_id}')
def update_visit(entity_id: int, item: Visit):
    with db() as c:
        ensure(c, 'visits', entity_id)
        values = validate_visit(c, item)
        c.execute('UPDATE visits SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), entity_id))
        audit(c, 'update', 'visits', entity_id)
        return ensure(c, 'visits', entity_id)


@app.get('/api/treatments')
def treatments():
    with db() as c:
        return rows(c, 'SELECT t.*,a.ear_tag,a.name animal_name,f.name farm_name,f.is_demo FROM treatments t JOIN animals a ON a.id=t.animal_id JOIN farms f ON f.id=a.farm_id ORDER BY t.treated_at DESC')


@app.post('/api/treatments', status_code=201)
def add_treatment(item: Treatment):
    with db() as c:
        ensure(c, 'animals', item.animal_id)
        at = item.treated_at.astimezone(timezone.utc)
        values = item.model_dump(exclude={'milk_days', 'meat_days'}, mode='json')
        values.update(treated_at=at.isoformat(timespec='seconds'),
                      milk_until=(at + timedelta(days=item.milk_days)).isoformat(timespec='seconds'),
                      meat_until=(at + timedelta(days=item.meat_days)).isoformat(timespec='seconds'))
        return save(c, 'treatments', values)


@app.get('/api/reports')
def reports():
    with db() as c:
        return rows(c, 'SELECT * FROM reports ORDER BY id DESC LIMIT 500')


@app.post('/api/reports', status_code=201)
def add_report(item: Report):
    values = item.model_dump()
    with db() as c:
        cur = c.execute('INSERT INTO reports (' + ','.join(values) + ',observed_at) VALUES (' + ','.join('?' for _ in values) + ',?)', (*values.values(), now()))
        audit(c, 'create', 'reports', cur.lastrowid)
        return ensure(c, 'reports', cur.lastrowid)


@app.patch('/api/reports/{entity_id}')
def review_report(entity_id: int, item: Review):
    with db() as c:
        ensure(c, 'reports', entity_id)
        c.execute('UPDATE reports SET verification=?,review_note=? WHERE id=?', (item.verification, item.review_note, entity_id))
        audit(c, 'review', 'reports', entity_id)
        return ensure(c, 'reports', entity_id)


@app.get('/api/sources')
def sources():
    return collector.source_status()


@app.post('/api/collect')
async def collect():
    return await collector.collect_all()


@app.get('/api/settings')
def settings():
    return {'ai_configured': bool(os.environ.get('VET_AI_API_KEY')), 'ai_model': os.environ.get('VET_AI_MODEL', 'gpt-4.1-mini'),
            'auto_collect': os.environ.get('VET_AUTO_COLLECT') == '1', 'collection_hours': 6,
            'mode': 'local-single-user', 'timezone': 'Europe/Warsaw'}


chat_lock = asyncio.Semaphore(2)


@app.post('/api/chat')
async def chat(item: Chat):
    async with chat_lock:
        return await agent.reply(item.message, item.history)


@app.get('/api/export/{entity}')
def export(entity: str):
    readers = {'farms': farms, 'animals': animals, 'visits': visits, 'treatments': treatments, 'reports': reports}
    if entity not in readers:
        raise HTTPException(404, 'Nieznany eksport')
    data = readers[entity]()
    stream = io.StringIO()
    if data:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        for row in data:
            # Prevent spreadsheet formula injection in free text fields.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v for k, v in row.items()})
    return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="stadovet-{entity}.csv"'})


@app.post('/api/demo')
def demo():
    with db() as c:
        if c.execute('SELECT count(*) FROM farms').fetchone()[0]:
            raise HTTPException(409, 'Dane pokazowe można wczytać tylko do pustej bazy gospodarstw.')
        today = datetime.now(ZoneInfo('Europe/Warsaw')).replace(hour=10, minute=0, second=0, microsecond=0)
        farm_data = [('Zielone Łąki', 'pomorskie', 'Kościerzyna'), ('Mazurska Zagroda', 'warmińsko-mazurskie', 'Mrągowo'), ('Podlaskie Pastwiska', 'podlaskie', 'Grajewo')]
        for i, (name, region, town) in enumerate(farm_data):
            farm = save(c, 'farms', {'name': name + ' [DEMO]', 'owner': 'Dane demonstracyjne', 'region': region, 'town': town, 'is_demo': 1})
            for j in range(4):
                a = save(c, 'animals', {'farm_id': farm['id'], 'ear_tag': f'DEMO{i+1:02d}{j+1:05d}', 'name': ['Łatka', 'Malina', 'Mela', 'Zorza'][j],
                                     'breed': 'Polska holsztyńsko-fryzyjska', 'sex': 'female', 'birth_date': f'202{j%3+1}-05-12', 'status': 'watch' if j == 0 else 'healthy'})
                if j == 0:
                    save(c, 'visits', {'farm_id': farm['id'], 'animal_id': a['id'], 'scheduled_at': (today + timedelta(days=i)).astimezone(timezone.utc).isoformat(timespec='seconds'), 'reason': ['Kontrola stada i profilaktyka', 'Badanie rozrodu', 'Kontrola żywienia'][i]})
        return {'message': 'Wczytano wyłącznie fikcyjne dane pokazowe. Nie utworzono sygnałów chorobowych.'}


@app.delete('/api/demo')
def delete_demo():
    with db() as c:
        # Visits may reference both farm and animal; remove every demo reference first.
        c.execute('DELETE FROM treatments WHERE animal_id IN (SELECT a.id FROM animals a JOIN farms f ON f.id=a.farm_id WHERE f.is_demo=1)')
        c.execute('DELETE FROM visits WHERE farm_id IN (SELECT id FROM farms WHERE is_demo=1) OR animal_id IN (SELECT a.id FROM animals a JOIN farms f ON f.id=a.farm_id WHERE f.is_demo=1)')
        c.execute('DELETE FROM animals WHERE farm_id IN (SELECT id FROM farms WHERE is_demo=1)')
        c.execute('DELETE FROM farms WHERE is_demo=1')
        audit(c, 'delete_demo', 'farms')
    return {'message': 'Usunięto gospodarstwa demonstracyjne wraz z ich zwierzętami, wizytami i leczeniem.'}


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')


app.mount('/static', StaticFiles(directory=STATIC), name='static')
