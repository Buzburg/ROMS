"""Push-to-talk local speech, with typed fallback and existing reviewed workshops."""
import argparse
from collections.abc import Iterator
from contextlib import closing
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time
import wave

from app.voice_audio import check_audio, play, record
from app.voice_chat import sentence_chunks, stream_answer
from app.voice_stt import TinyRecognizer
from app.voice_tts import PocketSpeaker

DATA_DIR = Path('/opt/goose-voice-data')


def read_wave(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), 'rb') as source:
        rate = source.getframerate()
        if (source.getnchannels() != 1 or source.getsampwidth() != 2
                or source.getcomptype() != 'NONE' or not 8000 <= rate <= 48000
                or not 0 < source.getnframes() <= rate * 30):
            raise ValueError('Use a mono 16-bit PCM WAV, up to 30 seconds at 8–48kHz.')
        expected = source.getnframes() * 2
        pcm = source.readframes(source.getnframes())
        if len(pcm) != expected:
            raise ValueError('The WAV recording is incomplete.')
        return pcm, rate


def speak(text: str, speaker: PocketSpeaker, cancel: threading.Event) -> float:
    if not text.strip() or len(text.encode('utf-8')) > 4096:
        raise ValueError('Spoken text must be nonempty and at most 4096 bytes.')
    def chunks() -> Iterator[object]:
        for sentence in sentence_chunks(iter([text])):
            yield from speaker.iter_audio(sentence, cancel)
    with closing(chunks()) as audio:
        return play(audio, speaker.sample_rate, cancel)


def reply(prompt: str, history: list[dict[str, str]], speaker: PocketSpeaker,
          cancel: threading.Event) -> None:
    if not prompt.strip() or len(prompt.encode('utf-8')) > 2048:
        raise ValueError('Please use a shorter request, up to 2048 bytes.')
    messages = history[-6:] + [{'role': 'user', 'content': prompt}]
    api_key = os.environ.get('ROMS_GATEWAY_API_KEY', '')
    if not api_key:
        raise RuntimeError('Start voice through goose --voice so local chat credentials are available.')
    print('ROMS is thinking. Ctrl+C stops this reply.', flush=True)
    answer: list[str] = []
    started = time.monotonic()
    parts = stream_answer(messages, api_key, cancel)
    def audio() -> Iterator[object]:
        for sentence in sentence_chunks(parts):
            answer.append(sentence)
            print(sentence, end=' ', flush=True)
            yield from speaker.iter_audio(sentence, cancel)
    print('\nROMS: ', end='', flush=True)
    try:
        with closing(audio()) as output:
            seconds = play(output, speaker.sample_rate, cancel)
    finally:
        cancel.set()
        parts.close()
        print()
    history.extend([{'role': 'user', 'content': prompt},
                    {'role': 'assistant', 'content': ' '.join(answer)}])
    del history[:-6]
    # Long past turns should never make the next short voice request unusable.
    while history and sum(len(item['content'].encode('utf-8')) for item in history) > 1400:
        del history[:2]
    print(f'Reply finished in {time.monotonic() - started:.1f}s; {seconds:.1f}s of speech.')


def _enter_pressed() -> bool:
    if select.select([sys.stdin], [], [], 0)[0]:
        sys.stdin.readline()
        return True
    return False


def interactive(recognizer: TinyRecognizer, speaker: PocketSpeaker) -> None:
    history: list[dict[str, str]] = []
    print('\nROMS voice is ready. Press Enter to talk, then Enter to send (30s maximum).')
    print('/type MESSAGE · /reset · /system · /project · /exit. Ctrl+C stops the current turn.')
    print('The microphone is off between recordings. System changes use the reviewed workshops.')
    while True:
        cancel = threading.Event()
        try:
            command = input('\nYou: ').strip()
            if command == '/exit':
                return
            if command == '/reset':
                history.clear()
                print('Conversation cleared.')
                continue
            if command in {'/system', '/project'}:
                subprocess.run(['/usr/local/bin/goose', '--system' if command == '/system'
                                else '--project-workshop'], check=False)
                continue
            if command.startswith('/type '):
                prompt = command[6:].strip()
            elif command:
                print('Use /type MESSAGE for typed chat, or Enter to use the microphone.')
                continue
            else:
                print('Connecting microphone… Ctrl+C cancels.', flush=True)
                pcm = record(_enter_pressed, cancel,
                             on_ready=lambda: print('Listening — Enter sends; Ctrl+C discards.', flush=True))
                try:
                    if len(pcm) < 6400:
                        print('Recording was too short. Try again.')
                        continue
                    print('Understanding your speech…', flush=True)
                    prompt = recognizer.transcribe(pcm)
                finally:
                    del pcm
                if not prompt.strip():
                    print('No speech recognized. Try again or use /type MESSAGE.')
                    continue
                print('You said:', prompt, flush=True)
            reply(prompt, history, speaker, cancel)
        except KeyboardInterrupt:
            cancel.set()
            print('\nTurn stopped. Microphone and playback closed.')
        except EOFError:
            return
        except (OSError, RuntimeError, ValueError) as error:
            cancel.set()
            print(f'Voice unavailable: {error}', file=sys.stderr)
        finally:
            cancel.set()


def main() -> None:
    parser = argparse.ArgumentParser(description='Local ROMS push-to-talk voice')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--say', help='Speak supplied text without recording or calling ROMS')
    mode.add_argument('--text', help='Ask ROMS once with typed input and hear the reply')
    mode.add_argument('--input-wav', type=Path, help='Transcribe one WAV and ask ROMS')
    mode.add_argument('--check', action='store_true', help='Check audio and load both local speech models')
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        raise SystemExit('Run ROMS voice inside Omarchy/Linux.')
    if os.geteuid() == 0:
        raise SystemExit('Run ROMS voice as your regular desktop user.')
    if not any((args.say, args.text, args.input_wav, args.check)) and not sys.stdin.isatty():
        raise SystemExit('Push-to-talk needs an interactive terminal.')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    print(check_audio(), flush=True)
    print('Loading local speech models…', flush=True)
    speaker = PocketSpeaker(DATA_DIR)
    recognizer = TinyRecognizer(DATA_DIR)
    cancel = threading.Event()
    try:
        speaker.load()
        if not args.say and not args.text:
            recognizer.load()
        if args.check:
            print('Local voice models and audio connection are ready. Microphone not opened.')
        elif args.say:
            speak(args.say, speaker, cancel)
        elif args.text:
            reply(args.text, [], speaker, cancel)
        elif args.input_wav:
            pcm, rate = read_wave(args.input_wav)
            try:
                prompt = recognizer.transcribe(pcm, rate)
            finally:
                del pcm
            print('You said:', prompt, flush=True)
            reply(prompt, [], speaker, cancel)
        else:
            interactive(recognizer, speaker)
    finally:
        cancel.set()
        recognizer.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nVoice closed.')
    except (OSError, RuntimeError, ValueError, wave.Error) as error:
        raise SystemExit(f'Voice unavailable: {error}') from error
