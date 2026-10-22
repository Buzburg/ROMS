#!/usr/bin/env python3
"""Install the reviewed Linux x86_64/Python 3.12 voice lock in separate /opt paths.

Without --apply this prints a plan. No packages are installed in /opt/roms-env.
The lock pins every wheel and model byte; no HF login, model execution, microphone,
service start, or system package installation is performed here. Failed installs
can resume with the identical lock; an unrelated existing directory is refused.
"""
from __future__ import annotations

import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from app.voice_tts import local_config

RUNTIME = Path("/opt/goose-voice-env")
DATA = Path("/opt/goose-voice-data")
BASE_PYTHON = Path("/opt/roms-env/bin/python")
LOCK = REPO_ROOT / "config/voice-runtime.json"
MARKER = ".goose-voice-lock-sha256"
_HASH = re.compile(r"[0-9a-f]{64}")
_WHEEL_HOSTS = {"files.pythonhosted.org", "download.pytorch.org", "download-r2.pytorch.org"}
_ASSET_HOSTS = {"huggingface.co", "download.moonshine.ai"}


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _check_url(url: Any, allowed: set[str]) -> None:
    if not isinstance(url, str) or any(char.isspace() for char in url):
        raise ValueError("Invalid locked download URL.")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in allowed
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise ValueError("Download URL is outside the reviewed public sources.")


def read_lock(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    if len(raw) > 131072:
        raise ValueError("Voice lock is too large.")
    lock = json.loads(raw)
    if (lock.get("schema_version") != 1 or lock.get("platform") != "linux-x86_64"
            or lock.get("python") != "3.12"):
        raise ValueError("Unsupported voice runtime lock.")
    packages, assets = lock["packages"], lock["assets"]
    if not 1 <= len(packages) <= 100 or not 1 <= len(assets) <= 64:
        raise ValueError("Invalid lock inventory.")
    names = set()
    for package in packages:
        _check_url(package["url"], _WHEEL_HOSTS)
        if (not package["url"].endswith(".whl") or not _HASH.fullmatch(package["sha256"])
                or package["name"].lower() in names):
            raise ValueError("Invalid wheel pin.")
        names.add(package["name"].lower())
    versions = {p["name"].lower(): p["version"] for p in packages}
    if (versions.get("pocket-tts") != "3.3.0"
            or versions.get("moonshine-voice") != "0.1.5"
            or versions.get("torch") != "2.8.0+cpu"):
        raise ValueError("Unexpected core runtime versions.")
    paths = set()
    for asset in assets:
        _check_url(asset["url"], _ASSET_HOSTS)
        name = asset["path"]
        if (not isinstance(name, str) or not re.fullmatch(r"(?:tts|moonshine|licenses)/[A-Za-z0-9_.-]+", name)
                or name in paths or not _HASH.fullmatch(asset["sha256"])
                or type(asset["size"]) is not int or not 0 < asset["size"] <= 500_000_000):
            raise ValueError("Invalid model asset pin.")
        if asset["url"].startswith("https://huggingface.co/"):
            if not re.match(r"https://huggingface.co/kyutai/(?:pocket-tts-without-voice-cloning|tts-voices)/resolve/[0-9a-f]{40}/", asset["url"]):
                raise ValueError("Unpinned or unapproved Hugging Face repository.")
        elif not asset["url"].startswith("https://download.moonshine.ai/model/tiny-streaming-en/quantized_26_08_21/"):
            raise ValueError("Unpinned Moonshine model.")
        paths.add(name)
    return lock, hashlib.sha256(raw).hexdigest()


def _environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": "/root", "LANG": "C.UTF-8",
            "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONNOUSERSITE": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1"}


def _run(args: list[str], *, timeout: int = 900) -> None:
    subprocess.run(args, check=True, timeout=timeout, env=_environment(), stdin=subprocess.DEVNULL)


def _prepare_directory(path: Path, fingerprint: str) -> None:
    if path.is_symlink():
        raise ValueError("Voice installation directory must not be a symlink.")
    path.mkdir(mode=0o755, parents=False, exist_ok=True)
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Voice installation directory must be protected and root-owned.")
    marker = path / MARKER
    if marker.exists():
        if marker.is_symlink() or marker.read_text() != fingerprint:
            raise ValueError("An existing voice runtime uses a different lock; preserve it before upgrading.")
    elif any(path.iterdir()):
        raise ValueError("Refusing to change an unrelated existing directory.")
    else:
        marker.write_text(fingerprint, encoding="ascii")


def _download(asset: dict[str, Any], data_dir: Path) -> None:
    target = data_dir / asset["path"]
    target.parent.mkdir(mode=0o755, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError("Model asset paths must not be symlinks.")
    if target.exists():
        if target.stat().st_size == asset["size"] and _sha256(target) == asset["sha256"]:
            return
        raise ValueError("An installed voice asset changed; refusing to overwrite it.")
    fd, temporary = tempfile.mkstemp(prefix=".voice-download-", dir=target.parent)
    os.close(fd)
    part = Path(temporary)
    try:
        # Moonshine documents that its public CDN requires curl (urllib UA is blocked).
        _run(["/usr/bin/curl", "-q", "--fail", "--silent", "--show-error", "--location",
              "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "20",
              "--max-time", "300", "--max-filesize", str(asset["size"]),
              "--output", str(part), asset["url"]], timeout=330)
        if part.stat().st_size != asset["size"] or _sha256(part) != asset["sha256"]:
            raise ValueError("Downloaded voice asset failed its pinned checksum.")
        part.chmod(0o644)
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def install(lock: dict[str, Any], fingerprint: str) -> None:
    if (sys.platform != "linux" or platform.machine() != "x86_64"
            or sys.version_info[:2] != (3, 12) or os.geteuid() != 0):
        raise ValueError("Run with /opt/roms-env/bin/python as root on Linux x86_64.")
    if not BASE_PYTHON.is_file() or not Path("/usr/bin/curl").is_file():
        raise ValueError("The base Python or system curl is unavailable.")
    if not ctypes.util.find_library("portaudio"):
        raise ValueError("System PortAudio is required for microphone and speaker access.")
    if Path("/opt").is_symlink() or Path("/opt").stat().st_mode & 0o022:
        raise ValueError("The /opt parent directory is not protected.")
    for directory in (RUNTIME, DATA):
        _prepare_directory(directory, fingerprint)
    python = RUNTIME / "bin/python"
    if not python.exists():
        print("Creating isolated Python 3.12 voice environment.", flush=True)
        _run([str(BASE_PYTHON), "-m", "venv", "--copies", str(RUNTIME)], timeout=120)
    requirements = RUNTIME / "voice-requirements.lock"
    requirements.write_text("\n".join(
        f"{p['url']} --hash=sha256:{p['sha256']}" for p in lock["packages"]) + "\n", encoding="utf-8")
    print("Installing pinned CPU-only voice wheels.", flush=True)
    _run([str(python), "-m", "pip", "install", "--no-index", "--no-deps",
          "--only-binary=:all:", "--require-hashes", "--quiet", "-r", str(requirements)])
    _run([str(python), "-m", "pip", "check"], timeout=60)
    for asset in lock["assets"]:
        print(f"Verifying asset: {asset['path']}", flush=True)
        _download(asset, DATA)
    config = DATA / "tts/pocket-english.yaml"
    config.write_text(json.dumps(local_config(DATA), indent=2) + "\n", encoding="utf-8")
    (DATA / "voice-runtime.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    (DATA / "NOTICE.txt").write_text(
        "ROMS local voice runtime\nPocket TTS weights: Kyutai, CC BY 4.0.\n"
        "Fixed Marius voice: Selfie, Kyutai Unmute voice donations, CC0.\n"
        "Moonshine Tiny Streaming: Moonshine AI, MIT.\n"
        "See licenses/pocket-model.md, licenses/voices.md and voice-runtime.json for exact sources.\n"
        "The Pocket configuration was changed to use verified local files only.\n", encoding="utf-8")
    print("Voice runtime installed; models and audio devices have not been started.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create only the fixed isolated /opt voice paths.")
    args = parser.parse_args()
    try:
        lock, fingerprint = read_lock(LOCK)
        if not args.apply:
            print(f"Plan: {len(lock['packages'])} pinned wheels, {len(lock['assets'])} assets; "
                  f"runtime {RUNTIME}, data {DATA}. Use --apply to install.")
            return 0
        install(lock, fingerprint)
        return 0
    except ValueError as exc:
        print(f"Voice installation stopped: {exc}", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, subprocess.SubprocessError):
        print("Voice installation failed. Check the prerequisite/download message above; "
              "the same lock can resume an incomplete install.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
