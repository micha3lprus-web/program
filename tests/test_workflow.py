from datetime import datetime, timedelta, timezone

from vetapp.db import db


def test_health_and_ui(client):
    assert client.get('/api/health').json()['status'] == 'ok'
    r = client.get('/')
    assert r.status_code == 200 and 'StadoVet' in r.text
    assert "script-src 'self'" in r.headers['content-security-policy']
    assert client.get('/static/app.js').status_code == 200


def test_farm_and_animal_persist(client, farm, animal):
    assert client.get('/api/farms').json()[0]['animal_count'] == 1
    detail = client.get(f"/api/animals/{animal['id']}").json()
    assert detail['farm']['id'] == farm['id']
    assert detail['treatments'] == []
    with db() as c:
        assert c.execute('SELECT ear_tag FROM animals').fetchone()[0] == animal['ear_tag']
        assert c.execute('SELECT count(*) FROM audit').fetchone()[0] == 2


def test_unique_ear_tag_normalized(client, animal):
    fields = {k: v for k, v in animal.items() if k not in ['id', 'created_at']}
    fields['ear_tag'] = 'pl 123456789012'
    assert client.post('/api/animals', json=fields).status_code == 409
    assert len(client.get('/api/animals').json()) == 1


def test_reject_unknown_farm_and_future_birth(client):
    fields = {'farm_id': 1234, 'ear_tag': 'PL0001', 'birth_date': '2020-01-01'}
    assert client.post('/api/animals', json=fields).status_code == 404
    fields['birth_date'] = '2999-01-01'
    assert client.post('/api/animals', json=fields).status_code == 422


def test_visit_cannot_reference_another_herd(client, animal):
    other = client.post('/api/farms', json={'name': 'Drugie', 'region': 'pomorskie'}).json()
    fields = {'farm_id': other['id'], 'animal_id': animal['id'], 'scheduled_at': '2027-07-01T10:00:00+02:00', 'reason': 'Kontrola stada'}
    assert client.post('/api/visits', json=fields).status_code == 422


def test_visit_crud_and_utc(client, animal):
    data = {'farm_id': animal['farm_id'], 'animal_id': animal['id'], 'scheduled_at': '2027-07-01T10:00:00+02:00', 'reason': 'Badanie kontrolne'}
    r = client.post('/api/visits', json=data)
    assert r.status_code == 201
    visit = r.json()
    assert visit['scheduled_at'] == '2027-07-01T08:00:00+00:00'
    assert client.put(f"/api/visits/{visit['id']}", json={**data, 'status': 'done'}).status_code == 200
    assert client.get('/api/overview').json()['planned_visits'] == 0


def test_naive_visit_time_rejected(client, farm):
    assert client.post('/api/visits', json={'farm_id': farm['id'], 'scheduled_at': '2027-01-01T12:00', 'reason': 'Kontrola'}).status_code == 422


def test_update_animal_status_and_no_transfer(client, animal):
    data = {k: v for k, v in animal.items() if k not in ['id', 'created_at']}
    data['status'] = 'watch'
    assert client.put('/api/animals/'+str(animal['id']), json=data).status_code == 200
    assert client.get('/api/overview').json()['attention'] == 1
    data['farm_id'] = 999
    assert client.put('/api/animals/'+str(animal['id']), json=data).status_code == 422


def treatment_data(animal):
    return {'animal_id': animal['id'], 'diagnosis': 'Wpis testowy', 'medication': 'Produkt testowy', 'dose': 'Dane testowe — nie stosować', 'vet': 'Lekarz testowy', 'treated_at': (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(), 'milk_days': 4, 'meat_days': 14}


def test_withdrawals_and_history(client, animal):
    fields = treatment_data(animal)
    r = client.post('/api/treatments', json=fields)
    assert r.status_code == 201
    result = r.json()
    start = datetime.fromisoformat(fields['treated_at']).replace(microsecond=0)
    assert datetime.fromisoformat(result['milk_until']) == start + timedelta(days=4)
    assert datetime.fromisoformat(result['meat_until']) == start + timedelta(days=14)
    assert client.get('/api/overview').json()['active_withdrawals'] == 1
    assert len(client.get(f"/api/animals/{animal['id']}").json()['treatments']) == 1


def test_multiple_treatments_keep_longest_withdrawal(client, animal):
    fields = treatment_data(animal)
    client.post('/api/treatments', json=fields)
    client.post('/api/treatments', json={**fields, 'milk_days': 0, 'meat_days': 0})
    assert client.get('/api/overview').json()['active_withdrawals'] == 1
    assert datetime.fromisoformat(client.get('/api/animals').json()[0]['milk_until']) > datetime.now(timezone.utc)


def test_negative_or_future_treatment_rejected(client, animal):
    fields = treatment_data(animal)
    assert client.post('/api/treatments', json={**fields, 'milk_days': -1}).status_code == 422
    assert client.post('/api/treatments', json={**fields, 'treated_at': '2999-01-01T00:00:00Z'}).status_code == 422
    assert client.get('/api/treatments').json() == []


def test_report_review_requires_note_and_never_confirms_outbreak(client):
    data = {'title': 'Sygnał testowy — bez rzeczywistego zdarzenia', 'region': 'podlaskie', 'source_name': 'Test', 'source_url': 'https://example.org/test'}
    r = client.post('/api/reports', json=data)
    assert r.status_code == 201 and r.json()['verification'] == 'unverified'
    id = r.json()['id']
    assert client.patch(f'/api/reports/{id}', json={'verification': 'reviewed', 'review_note': 'x'}).status_code == 422
    assert client.patch(f'/api/reports/{id}', json={'verification': 'confirmed', 'review_note': 'sprawdzono'}).status_code == 422
    assert client.patch(f'/api/reports/{id}', json={'verification': 'reviewed', 'review_note': 'Testowa ocena źródła'}).json()['verification'] == 'reviewed'
    assert client.post('/api/reports', json=data).status_code == 409


def test_export_formula_safety(client):
    client.post('/api/farms', json={'name': '=HYPERLINK(test)', 'region': 'podlaskie'})
    r = client.get('/api/export/farms')
    assert r.status_code == 200
    assert "'=HYPERLINK(test)" in r.text
    assert 'attachment' in r.headers['content-disposition']
    assert client.get('/api/export/secret').status_code == 404


def test_cross_site_write_and_rebinding_rejected(client):
    data = {'name': 'Gospodarstwo', 'region': 'podlaskie'}
    assert client.post('/api/farms', json=data, headers={'origin': 'https://bad.example'}).status_code == 403
    assert client.post('/api/farms', json=data, headers={'sec-fetch-site': 'cross-site'}).status_code == 403
    assert client.get('/api/farms', headers={'host': 'bad.example'}).status_code == 403
    assert client.get('/api/farms').json() == []


def test_demo_idempotent_and_preserves_real_data(client):
    assert client.post('/api/demo').status_code == 200
    assert client.get('/api/overview').json()['animals'] == 12
    assert client.post('/api/demo').status_code == 409
    client.post('/api/farms', json={'name': 'Prawdziwe gospodarstwo', 'region': 'pomorskie'})
    assert client.delete('/api/demo').status_code == 200
    assert client.get('/api/animals').json() == []
    assert client.get('/api/visits').json() == []
    assert client.get('/api/farms').json()[0]['name'] == 'Prawdziwe gospodarstwo'
    assert client.get('/api/reports').json() == []


def test_local_agent_uses_actual_data(client, animal):
    r = client.post('/api/chat', json={'message': 'Jakie mam stado?'})
    assert r.status_code == 200
    assert r.json()['mode'] == 'local'
    assert '1 gospodarstw i 1 zwierząt' in r.json()['answer']
    assert client.get('/api/settings').json()['ai_configured'] is False


def test_missing_record_is_404(client):
    assert client.get('/api/animals/9999').status_code == 404


def test_secret_values_not_exposed(client, monkeypatch):
    monkeypatch.setenv('VET_AI_API_KEY', 'not-a-real-key-do-not-expose')
    r = client.get('/api/settings')
    assert r.json()['ai_configured'] is True
    assert 'not-a-real-key-do-not-expose' not in r.text
