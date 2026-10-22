"""Bounded in-memory audio through the user's local PulseAudio session."""
from collections.abc import Callable, Iterable
import os
from pathlib import Path
import select
import stat
import subprocess
import threading
import time


class VoiceAudioError(RuntimeError):
    pass


class VoiceAudioCancelled(VoiceAudioError):
    pass


def audio_environment() -> dict[str, str]:
    runtime = Path(f'/run/user/{os.getuid()}')
    configured = os.environ.get('PULSE_SERVER', '')
    candidates = [configured] if configured else [
        f'unix:{runtime}/pulse/native', 'unix:/mnt/wslg/PulseServer']
    for server in candidates:
        if not server.startswith('unix:/'):
            continue
        path = Path(server[5:])
        try:
            if not stat.S_ISSOCK(path.stat().st_mode):
                continue
        except OSError:
            continue
        return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
                'LANG': 'C.UTF-8', 'XDG_RUNTIME_DIR': str(runtime),
                'PULSE_SERVER': server}
    raise VoiceAudioError('No local audio connection. Open ROMS in your desktop audio session.')


def check_audio() -> str:
    try:
        result = subprocess.run(['/usr/bin/pactl', 'info'], env=audio_environment(),
                                capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VoiceAudioError('Audio clients unavailable; install libpulse and check the audio session.') from error
    if result.returncode:
        raise VoiceAudioError('The local audio server is unavailable.')
    allowed = ('Default Sink:', 'Default Source:', 'Is Local:')
    return '\n'.join(line for line in result.stdout.decode('utf-8', 'replace').splitlines()
                     if line.startswith(allowed))


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def record(stop_requested: Callable[[], bool], cancel: threading.Event,
           duration: float = 30.0, on_ready: Callable[[], None] | None = None) -> bytes:
    """Capture mono 16kHz signed 16-bit PCM until release, cancellation or limit."""
    if not 0 < duration <= 30:
        raise ValueError('Recording limit must be between zero and 30 seconds.')
    if cancel.is_set():
        raise VoiceAudioCancelled('Recording stopped.')
    maximum = int(duration * 16000) * 2
    process = subprocess.Popen([
        '/usr/bin/parec', '--raw', '--format=s16le', '--rate=16000', '--channels=1',
        '--latency-msec=50', '--client-name=ROMS voice', '--stream-name=Push to talk'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=audio_environment(),
        start_new_session=True)
    data = bytearray()
    startup_deadline = time.monotonic() + 5
    deadline = None
    try:
        assert process.stdout is not None
        while len(data) < maximum:
            if cancel.is_set():
                raise VoiceAudioCancelled('Recording stopped.')
            if stop_requested():
                break
            now = time.monotonic()
            if deadline is None and now >= startup_deadline:
                raise VoiceAudioError('Microphone supplied no audio. Check microphone access and the selected input device.')
            if deadline is not None and now >= deadline:
                break
            if select.select([process.stdout], [], [], 0.05)[0]:
                chunk = os.read(process.stdout.fileno(), min(4096, maximum - len(data)))
                if not chunk:
                    raise VoiceAudioError('Microphone disconnected or access was denied.')
                if deadline is None:
                    deadline = time.monotonic() + duration
                    if on_ready:
                        on_ready()
                data.extend(chunk)
        return bytes(data[:len(data) - len(data) % 2])
    finally:
        _stop(process)
        if process.stdout:
            process.stdout.close()


def play(chunks: Iterable[object], sample_rate: int, cancel: threading.Event) -> float:
    """Play floating-point mono chunks with bounded buffering and cancellation."""
    import numpy as np
    if not 8000 <= sample_rate <= 48000:
        raise ValueError('Unsupported speech sample rate.')
    if cancel.is_set():
        raise VoiceAudioCancelled('Speech stopped.')
    process = subprocess.Popen([
        '/usr/bin/pacat', '--playback', '--raw', '--format=s16le',
        f'--rate={sample_rate}', '--channels=1', '--latency-msec=80',
        '--client-name=ROMS voice', '--stream-name=Spoken reply'],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=audio_environment(), start_new_session=True)
    samples = 0
    deadline = time.monotonic() + 180
    try:
        assert process.stdin is not None
        descriptor = process.stdin.fileno()
        os.set_blocking(descriptor, False)
        for chunk in chunks:
            if cancel.is_set():
                raise VoiceAudioCancelled('Speech stopped.')
            audio = np.asarray(chunk)
            if audio.ndim != 1 or not np.isfinite(audio).all():
                raise VoiceAudioError('Speech engine returned invalid audio.')
            samples += audio.size
            if samples > sample_rate * 90:
                raise VoiceAudioError('Spoken reply exceeded 90 seconds.')
            pcm = memoryview((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
            while pcm:
                if cancel.is_set():
                    raise VoiceAudioCancelled('Speech stopped.')
                if time.monotonic() >= deadline:
                    raise VoiceAudioError('Speaker playback timed out.')
                if process.poll() is not None:
                    raise VoiceAudioError('Speaker disconnected or access was denied.')
                if select.select([], [descriptor], [], 0.05)[1]:
                    try:
                        written = os.write(descriptor, pcm[:8192])
                    except BlockingIOError:
                        continue
                    pcm = pcm[written:]
        process.stdin.close()
        while process.poll() is None:
            if cancel.wait(0.05):
                raise VoiceAudioCancelled('Speech stopped.')
            if time.monotonic() >= deadline:
                raise VoiceAudioError('Speaker playback timed out.')
        if process.returncode:
            raise VoiceAudioError('Speaker playback failed.')
        return samples / sample_rate
    except BrokenPipeError as error:
        raise VoiceAudioError('Speaker disconnected.') from error
    finally:
        _stop(process)
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
