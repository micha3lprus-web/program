"""Build an offline Windows x64 installer on Linux using NSIS; never copy live data."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

import httpx

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PYTHON_VERSION = '3.13.17'
PYTHON_SHA512 = 'DmZ5KLtPGVc8bNiPZRM7LgeyQ6XHFvM1tWqma7nsb4IyglbSLDop4joCdqxcam14YhH+q1JIkK0eVmKRlsaynA=='
PYTHON_URL = f'https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def png_chunk(kind, content):
    return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content) & 0xffffffff)


def create_icon(path):
    glyph = ['01111', '11000', '11000', '01110', '00011', '00011', '11110']
    size = 64
    scanlines = bytearray()
    for y in range(size):
        scanlines.append(0)
        for x in range(size):
            radius = 13
            dx = max(radius - x, 0, x - (size - radius - 1))
            dy = max(radius - y, 0, y - (size - radius - 1))
            alpha = 0 if dx * dx + dy * dy > radius * radius else 255
            gx, gy = (x-13)//5, (y-14)//5
            on_s = 0 <= gx < 5 and 0 <= gy < 7 and glyph[gy][gx] == '1'
            on_plus = (46 <= x < 50 and 9 <= y < 25) or (40 <= x < 56 and 15 <= y < 19)
            scanlines.extend((230, 237, 197, alpha) if on_s or on_plus else (41, 79, 61, alpha))
    png = b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
    png += png_chunk(b'IDAT', zlib.compress(bytes(scanlines), 9)) + png_chunk(b'IEND', b'')
    header = struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', size, size, 0, 0, 1, 32, len(png), 22)
    path.write_bytes(header + png)


def inside(root, name):
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Unsafe archive member')
    return target


def build(args):
    work = Path(args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cache = work / 'cache'
    cache.mkdir(exist_ok=True)
    wheels = work / 'wheels'
    wheels.mkdir(exist_ok=True)
    payload = work / 'payload'
    archive = work / f'python.{PYTHON_VERSION}.nupkg'
    with httpx.Client(timeout=120) as client:
        if not archive.exists():
            response = client.get(PYTHON_URL)
            response.raise_for_status()
            archive.write_bytes(response.content)
        python_bytes = archive.read_bytes()
        if base64.b64encode(hashlib.sha512(python_bytes).digest()).decode() != PYTHON_SHA512:
            raise ValueError('Official Python package SHA512 mismatch; refusing to build')
        subprocess.run([sys.executable, '-m', 'pip', '--cache-dir', str(cache), 'download', '--only-binary=:all:',
                        '--platform', 'win_amd64', '--python-version', '313', '--implementation', 'cp', '--abi', 'cp313',
                        '-r', str(HERE / 'requirements.txt'), '--dest', str(wheels)], check=True)
        verified = []
        expected = {line.split('==')[0].replace('-', '_').lower(): line.split('==')[1]
                    for line in (HERE / 'requirements.txt').read_text().splitlines() if '==' in line}
        actual = {}
        for wheel in sorted(wheels.glob('*.whl')):
            name, version = wheel.name.split('-')[:2]
            normalized_name = name.replace('-', '_').lower()
            if normalized_name in actual or expected.get(normalized_name) != version:
                raise ValueError(f'Stale or duplicate wheel in build cache: {wheel.name}')
            actual[normalized_name] = version
            response = client.get(f'https://pypi.org/pypi/{name}/{version}/json')
            response.raise_for_status()
            matches = [p for p in response.json()['urls'] if p['filename'] == wheel.name]
            wheel_hash = digest(wheel.read_bytes())
            if len(matches) != 1 or matches[0]['digests']['sha256'] != wheel_hash:
                raise ValueError(f'Wheel checksum mismatch: {wheel.name}')
            verified.append({'filename': wheel.name, 'sha256': wheel_hash})
        if actual != expected:
            raise ValueError('Runtime wheels do not match the pinned requirements')
    if payload.exists():
        shutil.rmtree(payload)
    runtime = payload / 'runtime'
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(python_bytes)) as z:
        for item in z.infolist():
            if not item.filename.startswith('tools/') or item.is_dir():
                continue
            rel = item.filename[len('tools/'):]
            dest = inside(runtime, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(item))
    packages = runtime / 'Lib' / 'site-packages'
    for wheel in wheels.glob('*.whl'):
        with zipfile.ZipFile(wheel) as z:
            for item in z.infolist():
                if item.is_dir():
                    continue
                rel = item.filename
                if '.data/' in rel:
                    tail = rel.split('.data/', 1)[1]
                    kind, rel = tail.split('/', 1)
                    if kind not in {'purelib', 'platlib'}:
                        raise ValueError(f'Unsupported wheel data path: {item.filename}')
                dest = inside(packages, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(item))
    (runtime / 'python313._pth').write_text('.\nLib\nDLLs\nLib\\site-packages\n..\\app\nimport site\n', encoding='ascii')
    shutil.copytree(REPO / 'vetapp', payload / 'app' / 'vetapp', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(HERE / 'launcher.py', payload / 'launcher.py')
    shutil.copy2(REPO / 'LICENSE', payload / 'LICENSE.txt')
    shutil.copy2(HERE / 'INSTRUKCJA.txt', payload / 'INSTRUKCJA.txt')
    shutil.copy2(REPO / 'README.md', payload / 'app' / 'README.md')
    create_icon(payload / 'StadoVet.ico')
    manifest = {'app_version': '0.1.0', 'target': 'Windows 10/11 x64', 'python_version': PYTHON_VERSION,
                'python_source': PYTHON_URL, 'python_sha512_base64': PYTHON_SHA512, 'wheels': verified,
                'contains_user_database': False, 'contains_credentials': False}
    manifest['payload_files_sha256'] = {str(p.relative_to(payload)).replace('\\', '/'): digest(p.read_bytes())
                                        for p in sorted(payload.rglob('*')) if p.is_file()}
    (payload / 'BUILD-MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    out = REPO / 'dist'
    out.mkdir(exist_ok=True)
    installer = out / 'StadoVet-Setup-0.1.0-win64.exe'
    subprocess.run([args.makensis, '-V2', f'-DPAYLOAD={payload}', f'-DOUTPUT={installer}', str(HERE / 'installer.nsi')], check=True)
    (out / (installer.name + '.sha256')).write_text(digest(installer.read_bytes()) + '  ' + installer.name + '\n', encoding='ascii')
    print(json.dumps({'installer': str(installer), 'bytes': installer.stat().st_size, 'sha256': digest(installer.read_bytes()), 'wheels': len(verified)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', default=str(REPO / 'build' / 'windows'))
    parser.add_argument('--makensis', default='makensis')
    build(parser.parse_args())
