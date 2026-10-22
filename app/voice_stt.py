"""Offline CPU speech recognition; audio stays in memory and never opens a device."""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import struct
import threading
from typing import TYPE_CHECKING
import unicodedata

from app.json_protocol import unique_object

if TYPE_CHECKING:
    from moonshine_voice.transcriber import Transcriber

MOONSHINE_VERSION = '0.1.5'
MAX_AUDIO_SECONDS = 30
MAX_TRANSCRIPT_CHARS = 4096
MODEL_URL = 'https://download.moonshine.ai/model/tiny-streaming-en/quantized_26_08_21/'
# The v0.1.5 native model catalog pins these eight English Tiny assets.
MODEL_FILES = {
    'adapter.ort': 1319664,
    'cross_kv.ort': 1287544,
    'decoder_kv.ort': 32583720,
    'encoder.ort': 7675440,
    'frontend.model.ort': 23344,
    'frontend.weights.ort': 2093464,
    'streaming_config.json': 509,
    'tokenizer.bin': 249974,
}
# v0.1.5's native VAD shares process state. Never overlap recognizers here.
_RUNTIME_LOCK = threading.RLock()


def _verified_model_dir(data_dir: Path) -> Path:
    root = data_dir.resolve(strict=True)
    manifest_path = root / 'voice-runtime.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('Voice runtime manifest is missing or unsafe')
    with manifest_path.open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('Voice runtime manifest is too large')
    manifest = json.loads(raw, object_pairs_hook=unique_object)
    if (type(manifest) is not dict or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1):
        raise ValueError('Unsupported voice runtime manifest')
    stt = manifest.get('stt')
    if (type(stt) is not dict or stt.get('model_arch') != 'tiny_streaming'
            or stt.get('model_dir') != 'moonshine'):
        raise ValueError('Voice runtime must use English Tiny Streaming')
    assets = manifest.get('assets')
    if type(assets) is not list or not 1 <= len(assets) <= 64:
        raise ValueError('Invalid voice model inventory')
    entries = {}
    for asset in assets:
        if type(asset) is not dict or type(asset.get('path')) is not str:
            raise ValueError('Invalid voice model asset')
        name = asset['path']
        if name in entries:
            raise ValueError('Duplicate voice model asset')
        entries[name] = asset
    wanted = {f'moonshine/{name}' for name in MODEL_FILES}
    if {name for name in entries if name.startswith('moonshine/')} != wanted:
        raise ValueError('Incomplete or unexpected Tiny model inventory')
    model_dir = root / 'moonshine'
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise ValueError('Tiny model directory is missing or unsafe')
    if {path.name for path in model_dir.iterdir()} != set(MODEL_FILES):
        raise ValueError('Tiny model directory contains unexpected or missing files')
    for name, size in MODEL_FILES.items():
        entry = entries[f'moonshine/{name}']
        digest = entry.get('sha256')
        if (type(entry.get('size')) is not int or entry['size'] != size
                or type(digest) is not str or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or entry.get('url') != MODEL_URL + name):
            raise ValueError('Invalid Tiny model identity')
        path = model_dir / name
        if (path.is_symlink() or not path.is_file()
                or path.resolve(strict=True).parent != model_dir
                or path.stat().st_size != size):
            raise ValueError('Tiny model asset is missing or unsafe')
        with path.open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != digest:
            raise ValueError('Tiny model asset failed verification')
    return model_dir


class TinyRecognizer:
    """One loaded Tiny model, with a fresh finite stream for each utterance."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._transcriber: Transcriber | None = None

    def load(self) -> None:
        """Verify installed assets and cache the model in memory; never download."""
        with _RUNTIME_LOCK:
            if self._transcriber is not None:
                return
            model_dir = _verified_model_dir(self.data_dir)
            try:
                installed = metadata.version('moonshine-voice')
            except metadata.PackageNotFoundError as exc:
                raise RuntimeError('Install the pinned ROMS voice runtime first') from exc
            if installed != MOONSHINE_VERSION:
                raise RuntimeError(f'Moonshine Voice {MOONSHINE_VERSION} is required')
            from moonshine_voice.moonshine_api import ModelArch
            from moonshine_voice.transcriber import Transcriber

            self._transcriber = Transcriber(
                model_path=model_dir, model_arch=ModelArch.TINY_STREAMING,
                options={'ort_providers': 'CPU', 'return_audio_data': 'false',
                         'log_output_text': 'false', 'log_api_calls': 'false',
                         'log_ort_run': 'false', 'save_input_wav_path': '',
                         'identify_speakers': 'false', 'word_timestamps': 'false',
                         'decode_incomplete_lines': 'false'},
            )

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        """Recognize at most 30 seconds of mono signed 16-bit little-endian PCM."""
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 48000:
            raise ValueError('Sample rate must be an integer between 8000 and 48000')
        if (type(pcm) is not bytes or len(pcm) % 2
                or len(pcm) > sample_rate * 2 * MAX_AUDIO_SECONDS):
            raise ValueError('Audio must be mono s16le PCM lasting at most 30 seconds')
        with _RUNTIME_LOCK:
            if self._transcriber is None:
                raise RuntimeError('Load the Tiny recognizer before transcribing')
            if not pcm:
                return ''
            samples = [sample[0] / 32768.0 for sample in struct.iter_unpack('<h', pcm)]
            # A fresh stream prevents the previous recording leaking into the next.
            with self._transcriber.create_stream(update_interval=MAX_AUDIO_SECONDS + 1) as stream:
                stream.start()
                stream.add_audio(samples, sample_rate)
                transcript = stream.stop()
            if transcript is None or type(transcript.lines) is not list:
                raise RuntimeError('Speech recognition did not finish')
            texts = []
            for line in transcript.lines:
                if line.is_complete is not True or type(line.text) is not str:
                    raise RuntimeError('Speech recognition returned an unfinished line')
                texts.append(line.text)
            text = ' '.join(' '.join(texts).split())
            if (len(text) > MAX_TRANSCRIPT_CHARS
                    or any(unicodedata.category(char).startswith('C') for char in text)):
                raise RuntimeError('Speech recognition returned invalid text')
            return text

    def close(self) -> None:
        """Release native resources; safe before load and after a previous close."""
        with _RUNTIME_LOCK:
            if self._transcriber is not None:
                transcriber, self._transcriber = self._transcriber, None
                transcriber.close()
