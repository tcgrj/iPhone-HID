#!/usr/bin/env python3
"""Read-only readiness checks; never reads auth/config secrets or contacts a device/model."""
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def find_codex(explicit=None):
    """Use an override, PATH, or executable in official desktop app bundles."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return p if p.is_file() and os.access(p, os.X_OK) else None
    candidates = [shutil.which('codex')]
    for apps in (Path('/Applications'), Path.home() / 'Applications'):
        for app in ('ChatGPT.app', 'Codex.app'):
            candidates.extend((apps / app / 'Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
                               apps / app / 'Contents/Resources/codex'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate).resolve()
    return None


def main():
    failed = []
    def check(name, passed, detail=''):
        print(('OK   ' if passed else 'FAIL ') + name + (': ' + detail if detail else ''))
        if not passed:
            failed.append(name)
    check('macOS', sys.platform == 'darwin')
    check('project Python', Path(sys.prefix).resolve() == (ROOT / '.venv').resolve(), sys.version.split()[0])
    for package, expected in (('Pillow', '11.3.0'), ('pyserial', '3.5')):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = 'missing'
        check(package, version == expected, version)
    for name in ('brew', 'cmake', 'pkg-config', 'swiftc', 'gst-inspect-1.0'):
        check(name, bool(shutil.which(name)))
    for path in (ROOT / '.console-runtime/ocr', ROOT / 'wireless/.runtime/uxplay-build/uxplay'):
        check(str(path.relative_to(ROOT)), path.is_file() and os.access(path, os.X_OK))
    codex = find_codex(os.environ.get('CODEX_BIN'))
    check('Codex CLI', bool(codex), str(codex or 'install Codex CLI or set CODEX_BIN'))
    if codex:
        result = subprocess.run([str(codex), '--version'], capture_output=True, text=True, timeout=15)
        check('Codex executable', result.returncode == 0, result.stdout.strip()[:160])
    environment = dict(os.environ)
    plugins = ROOT / 'wireless/.runtime/gst-plugins'
    if plugins.is_dir():
        environment.update(GST_PLUGIN_SYSTEM_PATH_1_0=str(plugins), GST_PLUGIN_PATH_1_0='',
                           GST_REGISTRY=str(ROOT / 'wireless/.runtime/gst-registry.bin'))
    # gst-inspect may refresh its local registry cache; no media/phone session starts.
    if shutil.which('gst-inspect-1.0'):
        for element in ('avdec_h264', 'h264parse', 'videoconvert', 'jpegenc', 'multipartmux', 'tcpserversink'):
            try:
                result = subprocess.run(['gst-inspect-1.0', element], env=environment,
                                        capture_output=True, timeout=20)
                check('GStreamer ' + element, result.returncode == 0)
            except subprocess.TimeoutExpired:
                check('GStreamer ' + element, False, 'plugin scan timed out')
    print('No phone connection, authentication request, model call, or secret inspection performed.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
