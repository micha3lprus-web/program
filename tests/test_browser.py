"""End-to-end workflow against an isolated database and a real Chromium browser."""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture
def live_server(tmp_path):
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    env = {**os.environ, 'VET_DATABASE': str(tmp_path / 'browser.db'), 'VET_AUTO_COLLECT': '0'}
    env.pop('VET_AI_API_KEY', None)
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'vetapp.main:app', '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail(process.stderr.read().decode())
            try:
                if httpx.get(base+'/api/health', timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.05)
        else:
            pytest.fail('Serwer nie osiągnął gotowości')
        yield base
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_full_browser_workflow(live_server):
    with sync_playwright() as p:
        executable = os.environ.get('CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome')
        browser = p.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, timezone_id='Europe/Warsaw')
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(live_server)
        expect(page.get_by_role('heading', name='Dzień dobry. Zadbajmy o stado.')).to_be_visible()
        page.get_by_role('button', name='Wczytaj dane pokazowe').click()
        expect(page.get_by_text('Dane demonstracyjne — fikcyjne', exact=False)).to_be_visible()
        Path('test-results').mkdir(exist_ok=True)
        page.screenshot(path='test-results/dashboard.png', full_page=True)
        page.get_by_role('link', name='Gospodarstwa', exact=True).click()
        page.get_by_role('button', name='Dodaj gospodarstwo', exact=True).click()
        page.get_by_label('Nazwa gospodarstwa').fill('Gospodarstwo testu E2E')
        page.get_by_label('Województwo').select_option('podlaskie')
        page.get_by_label('Miejscowość').fill('Grajewo')
        page.get_by_role('button', name='Zapisz', exact=True).click()
        expect(page.get_by_role('heading', name='Gospodarstwo testu E2E')).to_be_visible()

        page.get_by_role('link', name='Rejestr bydła').click()
        page.get_by_role('button', name='Dodaj zwierzę').click()
        page.get_by_label('Gospodarstwo', exact=True).select_option(label='Gospodarstwo testu E2E')
        page.get_by_label('Numer kolczyka').fill('TEST12345678')
        page.get_by_label('Imię (opcjonalnie)').fill('Testowa Malina')
        page.get_by_label('Data urodzenia').fill('2022-05-12')
        page.get_by_role('button', name='Zapisz', exact=True).click()
        expect(page.get_by_text('TEST12345678', exact=True)).to_be_visible()
        page.get_by_label('Szukaj zwierząt').fill('TEST12345678')
        expect(page.locator('tbody tr')).to_have_count(1)
        page.get_by_text('TEST12345678', exact=True).click()
        expect(page.get_by_role('heading', name='Testowa Malina')).to_be_visible()
        page.get_by_role('button', name='Zapisz leczenie', exact=True).click()
        page.get_by_label('Rozpoznanie lekarza').fill('TEST — nie jest zaleceniem medycznym')
        page.get_by_label('Lek / produkt').fill('TEST bez leku')
        page.get_by_label('Podana dawka').fill('TEST nie stosować')
        page.get_by_label('Lekarz prowadzący').fill('Lekarz testowy')
        page.get_by_label('Karencja na mleko').fill('4')
        page.get_by_label('Karencja na mięso').fill('14')
        page.get_by_role('button', name='Zapisz', exact=True).click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        page.get_by_role('link', name='Leczenie i karencje').click()
        expect(page.get_by_text('TEST bez leku', exact=False)).to_be_visible()
        expect(page.get_by_text('Obowiązuje', exact=True)).to_have_count(2)

        page.get_by_role('link', name='Wizyty', exact=True).click()
        page.get_by_role('button', name='Zaplanuj wizytę', exact=True).click()
        page.get_by_label('Gospodarstwo', exact=True).select_option(label='Gospodarstwo testu E2E')
        page.get_by_label('Zwierzę (opcjonalnie)').select_option(label='TEST12345678 · Testowa Malina')
        page.get_by_label('Cel wizyty').fill('Wizyta testowa E2E')
        page.get_by_role('button', name='Zapisz', exact=True).click()
        expect(page.get_by_text('Wizyta testowa E2E', exact=True)).to_be_visible()
        row = page.get_by_role('row').filter(has_text='Wizyta testowa E2E')
        row.get_by_role('button', name='Zakończ wizytę').click()
        page.get_by_role('dialog').get_by_role('button', name='Zakończ wizytę').click()
        expect(row.get_by_text('Zakończona')).to_be_visible()

        page.get_by_role('link', name='Sygnały regionalne').click()
        page.get_by_role('button', name='Dodaj sygnał').click()
        page.get_by_label('Tytuł / problem').fill('TEST materiału regionalnego — nieprawdziwe zdarzenie')
        page.get_by_label('Nazwa źródła').fill('Test E2E')
        page.get_by_label('Publiczny odnośnik').fill('https://example.org/test-e2e')
        page.get_by_role('button', name='Zapisz', exact=True).click()
        expect(page.get_by_role('heading', name='TEST materiału regionalnego', exact=False)).to_be_visible()
        page.get_by_role('button', name='Oceń materiał', exact=False).click()
        page.get_by_label('Wynik oceny').select_option('dismissed')
        page.get_by_label('Uzasadnienie').fill('Dane wyłącznie testowe.')
        page.get_by_role('button', name='Zapisz', exact=True).click()
        expect(page.locator('#list-content').get_by_text('Odrzucono', exact=True)).to_be_visible()

        page.get_by_role('link', name='Asystent AI', exact=False).click()
        page.get_by_label('Wiadomość do asystenta').fill('Jakie wizyty mam zaplanowane?')
        page.get_by_role('button', name='Wyślij wiadomość').click()
        expect(page.get_by_text('Kontrola stada i profilaktyka', exact=False)).to_be_visible()
        page.get_by_role('link', name='Źródła i ustawienia').click()
        page.get_by_role('button', name='Usuń dane pokazowe').click()
        page.get_by_role('dialog').get_by_role('button', name='Usuń dane pokazowe').click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        assert len(httpx.get(live_server+'/api/farms').json()) == 1
        assert len(httpx.get(live_server+'/api/animals').json()) == 1
        assert len(httpx.get(live_server+'/api/treatments').json()) == 1
        assert len(httpx.get(live_server+'/api/reports').json()) == 1

        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='Otwórz menu').click()
        page.get_by_role('link', name='Rejestr bydła').click()
        expect(page.get_by_role('heading', name='Rejestr bydła')).to_be_visible()
        expect(page.locator('#sidebar')).to_have_css('transform', 'matrix(1, 0, 0, 1, -248, 0)')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='test-results/mobile.png', full_page=True)
        assert not errors, errors
        browser.close()
