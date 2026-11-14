"""Start a headless AirPlay receiver; images are streamed to loopback, never recorded."""

import os
from pathlib import Path
import secrets
import shutil
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    runtime = root / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    local = runtime / 'uxplay-build' / 'uxplay'
    binary = str(local) if local.is_file() else shutil.which('uxplay')
    if not binary:
        raise SystemExit('Install UxPlay and GStreamer first; see wireless/README.md')
    environment = dict(os.environ)
    plugins = runtime / 'gst-plugins'
    if plugins.is_dir():
        environment.update(GST_PLUGIN_SYSTEM_PATH_1_0=str(plugins), GST_PLUGIN_PATH_1_0='',
                           GST_REGISTRY=str(runtime / 'gst-registry.bin'))
    pin = str(secrets.randbelow(9000) + 1000)
    print('Receiver: TechGe iPhone Screen | first connection PIN: ' + pin, flush=True)
    pipeline = ('queue leaky=downstream max-size-buffers=1 ! '
                'videoconvert ! video/x-raw,format=I420 ! '
                'jpegenc quality=85 ! multipartmux boundary=frame ! '
                'tcpserversink host=127.0.0.1 port=8767')
    command = [binary, '-n', 'TechGe iPhone Screen', '-nh', '-p', '7110', '-pin', pin,
               '-reg', str(runtime / 'airplay-clients'), '-vsync', 'no', '-as', '0',
               '-s', '1280x720', '-fps', '30', '-vd', 'avdec_h264 max-threads=1', '-vs', pipeline]
    # Keep the supervised PID as the receiver itself, not a wrapper with an
    # orphanable child. The assertion ends when that PID exits.
    if shutil.which('caffeinate'):
        subprocess.Popen(['caffeinate', '-i', '-w', str(os.getpid())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chdir(runtime)
    os.execvpe(binary, command, environment)


if __name__ == '__main__':
    main()
