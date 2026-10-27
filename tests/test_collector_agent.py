import asyncio
import json
import httpx

from vetapp import collector, agent


def test_parser_regions_and_source_provenance():
    html = '''<nav><a href="/topic/1">Bydło choroby podlaskie</a></nav>
    <a href="/forum/topic/2/?ref=x">Choroby bydła — podlaskie</a>
    <a href="/forum/topic/2/">Choroby bydła — podlaskie</a>
    <a href="/forum/topic/3/">Mastitis u krów — problem w stadzie</a>
    <a href="https://evil.example/a">Choroby bydła — pomorskie</a>
    <a href="/profile/1">Choroby bydła — warmińsko-mazurskie</a>'''
    found = collector.parse_links(html, collector.SOURCES[1])
    assert len(found) == 2
    assert found[0]['region'] == 'podlaskie'
    assert found[0]['source_kind'] == 'forum'
    assert found[1]['region'] == 'ogólnopolskie / nieustalone'
    assert found[1]['category'] == 'wymię i mleko'


def test_regions_and_contact_redaction():
    assert collector.regions_for('Bydło w woj. warmińsko-mazurskim') == ['warmińsko-mazurskie']
    assert collector.regions_for('Problemy bydła — pomorskie') == ['pomorskie']
    assert collector.regions_for('Problemy bydła — zachodniopomorskie') == ['ogólnopolskie / nieustalone']
    title = collector.clean_title('Kontakt 123 456 789 i rolnik@example.org')
    assert '123' not in title and 'example.org' not in title


def test_robots_disallow_prevents_page_fetch(client):
    urls = []
    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, text='User-agent: *\nDisallow: /')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await collector.collect_source(c, collector.SOURCES[0])
    result = asyncio.run(run())
    assert result['status'] == 'blocked'
    assert len(urls) == 1 and urls[0].endswith('/robots.txt')
    assert client.get('/api/reports').json() == []


def test_redirect_to_unapproved_host_blocked(client):
    def handler(request):
        return httpx.Response(302, headers={'location': 'https://internal.example/private'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await collector.collect_source(c, collector.SOURCES[0])
    assert asyncio.run(run())['status'] == 'error'


def test_collection_deduplicates_realistic_public_titles(client):
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        return httpx.Response(200, text='<a href="/forum/topic/123/">Problemy bydła w województwie podlaskim</a>')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            first = await collector.collect_source(c, collector.SOURCES[1])
            second = await collector.collect_source(c, collector.SOURCES[1])
            return first, second
    first, second = asyncio.run(run())
    assert first['added'] == 1 and second['added'] == 0
    reports = client.get('/api/reports').json()
    assert len(reports) == 1
    assert reports[0]['verification'] == 'unverified'
    assert reports[0]['published_at'] is None


def test_failed_source_does_not_create_fake_reports(client):
    def handler(request):
        raise httpx.ProxyError('403 Forbidden')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await collector.collect_source(c, collector.SOURCES[0])
    result = asyncio.run(run())
    assert result['status'] == 'error' and result['added'] == 0
    assert client.get('/api/reports').json() == []
    assert client.get('/api/sources').json()[0]['last_run']['status'] == 'error'


def test_ai_agent_tool_roundtrip_omits_farm_contacts(client, farm, monkeypatch):
    monkeypatch.setenv('VET_AI_API_KEY', 'test-key')
    calls = []
    real_client = httpx.AsyncClient
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'read_records', 'arguments': '{"kind":"farms"}'}}]}}]})
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': 'Odczytałem gospodarstwo z bazy.'}}]})
    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    r = client.post('/api/chat', json={'message': 'Pokaż gospodarstwa'})
    assert r.json()['mode'] == 'ai'
    assert r.json()['tools_used'] == ['farms']
    tool_data = json.loads(calls[1]['messages'][-1]['content'])
    assert tool_data[0]['name'] == farm['name']
    assert 'owner' not in tool_data[0] and 'phone' not in tool_data[0]
    assert calls[0]['store'] is False


def test_ai_auth_failure_is_explicit_fallback(client, monkeypatch):
    monkeypatch.setenv('VET_AI_API_KEY', 'test-key')
    real_client = httpx.AsyncClient
    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(401)), **kwargs))
    r = client.post('/api/chat', json={'message': 'Pomoc'})
    assert r.json()['mode'] == 'fallback'
    assert 'niedostępny' in r.json()['answer']
