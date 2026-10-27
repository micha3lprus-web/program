"""Exercise the generated installer and bundled Windows runtime in a disposable Wine prefix.

Requires WINE_BINARY and a ready WINEPREFIX. No host Python or network is used by the payload.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'dist' / 'StadoVet-Setup-0.1.0-win64.exe'
PREFIX = Path(os.environ['WINEPREFIX'])
WINE = os.environ['WINE_BINARY']
ENV = {**os.environ, 'VET_AUTO_COLLECT': '0'}
LOGS = PREFIX.parent / 'installer-tests'
LOGS.mkdir(exist_ok=True)


def winpath(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def run(*args, name='command', timeout=90):
    with (LOGS / f'{name}.log').open('w') as log:
        p = subprocess.run([WINE, *map(str, args)], env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    text = (LOGS / f'{name}.log').read_text(errors='replace')
    assert p.returncode == 0, f'{name}: {p.returncode}\n{text[-4000:]}'
    return text


def start(installed):
    log = (LOGS / 'server.log').open('a')
    proc = subprocess.Popen([WINE, str(installed / 'runtime' / 'pythonw.exe'), winpath(installed / 'launcher.py'), '--no-browser'], env=ENV, stdout=log, stderr=subprocess.STDOUT)
    data = installed.parents[1] / 'StadoVet'
    for _ in range(200):
        if proc.poll() is not None:
            raise AssertionError('Desktop launcher exited: ' + (LOGS / 'server.log').read_text(errors='replace')[-4000:])
        try:
            state = json.loads((data / 'server.json').read_text())
            base = f"http://127.0.0.1:{state['port']}"
            if httpx.get(base + '/api/health', timeout=1, trust_env=False).status_code == 200:
                return proc, data, base
        except (OSError, ValueError, httpx.HTTPError):
            pass
        time.sleep(.1)
    proc.terminate()
    raise AssertionError('Desktop server failed readiness; see server.log')


def main():
    run(OUTPUT, '/S', name='install')
    matches = list((PREFIX / 'drive_c' / 'users').glob('*/AppData/Local/Programs/StadoVet'))
    assert len(matches) == 1, matches
    installed = matches[0]
    result = run(installed / 'runtime' / 'python.exe', winpath(installed / 'launcher.py'), '--self-test', name='windows-runtime')
    assert '"status": "ok"' in result and '"platform": "win32"' in result, result
    proc, data, base = start(installed)
    with httpx.Client(base_url=base, timeout=10, trust_env=False) as c:
        r = c.post('/api/farms', json={'name': 'TEST zachowania bazy instalatora', 'region': 'podlaskie'})
        assert r.status_code == 201, r.text
    first_state = json.loads((data / 'server.json').read_text())
    run(installed / 'runtime' / 'pythonw.exe', winpath(installed / 'launcher.py'), '--no-browser', name='second-launch')
    assert json.loads((data / 'server.json').read_text())['pid'] == first_state['pid']
    # Upgrading a running app must stop its server and retain the actual database.
    run(OUTPUT, '/S', name='upgrade-running')
    proc.wait(timeout=20)
    proc, data, base = start(installed)
    assert httpx.get(base + '/api/farms', trust_env=False).json()[0]['name'] == 'TEST zachowania bazy instalatora'
    run(installed / 'runtime' / 'pythonw.exe', winpath(installed / 'launcher.py'), '--stop', name='stop')
    proc.wait(timeout=20)
    assert not (data / 'server.json').exists()
    # A crashed previous process must not prevent stopping/upgrading an idle app.
    (data / 'server.json').write_text('{"pid":999999,"port":1}')
    run(installed / 'runtime' / 'pythonw.exe', winpath(installed / 'launcher.py'), '--stop', name='stale-state')
    assert not (data / 'server.json').exists()
    run(installed / 'Odinstaluj.exe', '/S', name='uninstall')
    for _ in range(100):
        if not (installed / 'runtime').exists():
            break
        time.sleep(.1)
    assert not (installed / 'runtime').exists()
    assert (data / 'vet.db').exists()
    with sqlite3.connect(data / 'vet.db') as c:
        assert c.execute('SELECT name FROM farms').fetchone()[0] == 'TEST zachowania bazy instalatora'
    expected = (ROOT / 'dist' / (OUTPUT.name + '.sha256')).read_text().split()[0]
    assert hashlib.sha256(OUTPUT.read_bytes()).hexdigest() == expected
    print(json.dumps({'installer': 'passed', 'bundled_windows_runtime': 'passed', 'local_api': 'passed', 'single_instance': 'passed', 'upgrade_preserves_database': 'passed', 'stop': 'passed', 'uninstall_preserves_database': 'passed', 'native_windows_test': False}))


if __name__ == '__main__':
    main()
