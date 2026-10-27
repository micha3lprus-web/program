"""Windows desktop entry point, run by the bundled pythonw.exe. No user Python needed."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

APP = Path(__file__).resolve().parent / 'app'
sys.path.insert(0, str(APP))


def error(message):
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, message, 'StadoVet', 0x10)
    elif sys.stderr:
        print(message, file=sys.stderr)


def local_get(url):
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2)


def self_test():
    import tempfile
    from zoneinfo import ZoneInfo
    from datetime import datetime
    with tempfile.TemporaryDirectory(prefix='StadoVet-test-') as folder:
        os.environ['VET_DATABASE'] = str(Path(folder) / 'test.db')
        os.environ['VET_AUTO_COLLECT'] = '0'
        from fastapi.testclient import TestClient
        from vetapp.main import app
        with TestClient(app) as client:
            assert client.get('/api/health').json()['status'] == 'ok'
            assert client.get('/').status_code == 200
            farm = client.post('/api/farms', json={'name': 'TEST instalatora', 'region': 'podlaskie'})
            assert farm.status_code == 201, farm.text
            animal = client.post('/api/animals', json={'farm_id': farm.json()['id'], 'ear_tag': 'TEST0001', 'birth_date': '2022-01-01'})
            assert animal.status_code == 201, animal.text
            assert client.get('/api/overview').json()['animals'] == 1
            assert client.get('/api/export/animals').status_code == 200
        zone = datetime(2026, 7, 1, tzinfo=ZoneInfo('Europe/Warsaw')).utcoffset()
        assert zone.total_seconds() == 7200
    print(json.dumps({'status': 'ok', 'python': sys.version.split()[0], 'platform': sys.platform, 'database': 'ok', 'timezone': 'Europe/Warsaw', 'api': 'ok'}))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'StadoVet'
    root.mkdir(parents=True, exist_ok=True)
    state_path, stop_path = root / 'server.json', root / 'stop.flag'
    kernel = None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.OpenMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]

    def running():
        if kernel:
            handle = kernel.OpenMutexW(0x00100000, False, 'Local\\StadoVet.Desktop.1')
            if not handle:
                return False
            kernel.CloseHandle(handle)
            return True
        return state_path.exists()

    if args.stop:
        if not running():
            state_path.unlink(missing_ok=True)
            stop_path.unlink(missing_ok=True)
            return 0
        for _ in range(150):
            stop_path.touch()
            if not running():
                state_path.unlink(missing_ok=True)
                stop_path.unlink(missing_ok=True)
                return 0
            time.sleep(.1)
        error('Nie udało się zatrzymać StadoVet. Zamknij program przed aktualizacją.')
        return 1

    # Named mutex is scoped to the Windows logon session; it survives browser closure.
    mutex = None
    if os.name == 'nt':
        mutex = kernel.CreateMutexW(None, False, 'Local\\StadoVet.Desktop.1')
        if not mutex:
            error('Nie udało się uruchomić blokady programu.')
            return 1
        if ctypes.get_last_error() == 183:
            for _ in range(80):
                try:
                    state = json.loads(state_path.read_text(encoding='utf-8'))
                    address = f"http://127.0.0.1:{int(state['port'])}"
                    with local_get(address + '/api/health') as response:
                        if json.load(response).get('status') == 'ok':
                            if not args.no_browser:
                                webbrowser.open(address)
                            kernel.CloseHandle(mutex)
                            return 0
                except (OSError, ValueError, KeyError):
                    time.sleep(.1)
            kernel.CloseHandle(mutex)
            error('StadoVet jest uruchamiany. Spróbuj ponownie za chwilę lub użyj skrótu „Zatrzymaj StadoVet”.')
            return 1

    # pythonw has no std streams; provide real log streams for libraries and errors.
    handler = RotatingFileHandler(root / 'startup.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s', force=True)
    if sys.stdout is None:
        sys.stdout = open(root / 'console.log', 'a', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = sys.stdout
    os.environ['VET_DATABASE'] = str(root / 'vet.db')
    os.environ.setdefault('VET_AUTO_COLLECT', '1')
    stop_path.unlink(missing_ok=True)
    server = None
    thread = None
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            bound.bind(('127.0.0.1', 8765))
        except OSError:
            bound.bind(('127.0.0.1', 0))
        bound.listen(128)
        port = bound.getsockname()[1]
        address = f'http://127.0.0.1:{port}'
        import uvicorn
        config = uvicorn.Config('vetapp.main:app', host='127.0.0.1', port=port, ws='none', access_log=False, log_config=None)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={'sockets': [bound]}, daemon=True)
        thread.start()
        state_path.write_text(json.dumps({'pid': os.getpid(), 'port': port}), encoding='utf-8')
        for _ in range(200):
            if not thread.is_alive():
                raise RuntimeError('Serwer zakończył działanie podczas startu')
            if server.started:
                with local_get(address + '/api/health') as response:
                    if json.load(response).get('status') == 'ok':
                        break
            time.sleep(.1)
        else:
            raise RuntimeError('Serwer nie osiągnął gotowości')
        if not args.no_browser:
            webbrowser.open(address)
        logging.info('StadoVet started, port %s', port)
        while thread.is_alive() and not stop_path.exists():
            time.sleep(.3)
        if not thread.is_alive() and not stop_path.exists():
            raise RuntimeError('Serwer został nieoczekiwanie zatrzymany')
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception('Startup failure')
        error(f'Nie udało się uruchomić StadoVet. Szczegóły zapisano w:\n{root / "startup.log"}')
        return 1
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=12)
        bound.close()
        state_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == '__main__':
    raise SystemExit(main())
