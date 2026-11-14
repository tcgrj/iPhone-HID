"""Generate launchd plists for this checkout. Never install, load or restart services.

Keep the checkout at its permanent location and run scripts/setup-macos.sh there first.
Virtual environments are deliberately NOT copied: their paths are not relocatable.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import plistlib
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'scripts'))
    from doctor import find_codex
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='explicitly generate files; no service activation')
    parser.add_argument('--output-dir', type=Path, help='required destination for generated plists (no default install location)')
    parser.add_argument('--siri-host', help='optional Mac LAN IPv4 bind address; omit to disable the Siri gateway')
    parser.add_argument('--codex-bin', help='optional absolute Codex CLI executable path')
    parser.add_argument('--service', choices=('both', 'console', 'receiver'), default='both')
    args = parser.parse_args()
    if not args.generate or args.output_dir is None:
        parser.error('choose --generate and --output-dir explicitly; no services will be activated')
    if args.siri_host:
        try:
            ipaddress.IPv4Address(args.siri_host)
        except ValueError:
            parser.error('--siri-host must be an IPv4 address')
    python = root / '.venv/bin/python'
    if not python.is_file():
        parser.error('run scripts/setup-macos.sh from the permanent checkout location first')
    codex = find_codex(args.codex_bin or os.environ.get('CODEX_BIN'))
    if args.service != 'receiver' and codex is None:
        parser.error('Codex CLI not found; use --codex-bin /absolute/path/to/codex')
    requirements = []
    if args.service != 'console':
        requirements.append(root / 'wireless/.runtime/uxplay-build/uxplay')
    if args.service != 'receiver':
        requirements.append(root / '.console-runtime/ocr')
    for required in requirements:
        if not required.is_file():
            parser.error('missing build artifact: ' + str(required))
    runtime = root / 'wireless/.runtime'
    logs = runtime / 'logs'
    output = args.output_dir.expanduser().resolve()
    commands = {
        'cn.techge.iphone.receiver': [str(python), '-u', str(root / 'wireless/tools/run_receiver.py')],
        'cn.techge.iphone.console': [str(python), '-u', '-m', 'wireless.console.server'],
    }
    if args.siri_host:
        commands['cn.techge.iphone.console'] += ['--siri-host', args.siri_host]
    selected = {label: command for label, command in commands.items()
                if args.service == 'both' or label.endswith('.' + args.service)}
    # Refuse every conflict before writing any file; never overwrite an installed service.
    for label in selected:
        if (output / (label + '.plist')).exists():
            parser.error('destination already exists; choose a new output directory: ' + label)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = ([str(codex.parent)] if codex else []) + ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
    for label, command in selected.items():
        log = logs / (label + '.log')
        configuration = {
            'Label': label, 'ProgramArguments': command, 'WorkingDirectory': str(root),
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
            'ProcessType': 'Background',
            'EnvironmentVariables': {'PATH': ':'.join(path), 'PYTHONUNBUFFERED': '1'},
            'StandardOutPath': str(log), 'StandardErrorPath': str(log),
        }
        target = output / (label + '.plist')
        with target.open('xb') as handle:
            handle.write(plistlib.dumps(configuration))
        target.chmod(0o600)
        print('Generated:', target)
    print('No services installed or started. Review the plists before manually installing them.')
    print('If you move this checkout, recreate .venv with setup-macos.sh and generate new plists.')


if __name__ == '__main__':
    main()
