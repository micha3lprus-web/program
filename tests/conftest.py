import pytest
from fastapi.testclient import TestClient
from vetapp.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('VET_DATABASE', str(tmp_path / 'test.db'))
    monkeypatch.delenv('VET_AI_API_KEY', raising=False)
    monkeypatch.delenv('VET_AUTO_COLLECT', raising=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def farm(client):
    r = client.post('/api/farms', json={'name': 'Testowe gospodarstwo', 'region': 'podlaskie'})
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def animal(client, farm):
    r = client.post('/api/animals', json={'farm_id': farm['id'], 'ear_tag': 'PL123456789012', 'name': 'Malina', 'sex': 'female', 'birth_date': '2022-01-03'})
    assert r.status_code == 201
    return r.json()
