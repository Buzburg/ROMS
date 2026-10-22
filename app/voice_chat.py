"""Bounded, text-only local chat for the voice interface; never executes tools."""
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import codecs
import http.client
import json
import socket
import threading
import time
import unicodedata


_PORT = 8844
_TOTAL_TIMEOUT = 60.0
_MAX_TEXT_BYTES = 16 * 1024
_MAX_WIRE_BYTES = 128 * 1024
_SYSTEM = (
    "You are ROMS. Reply in 1-3 short spoken sentences. No reasoning, code, markup, "
    "or tool calls. You cannot perform actions. Never claim you ran commands, "
    "controlled apps, or changed files; explain what the user can do."
)


class VoiceChatError(RuntimeError):
    """Chat was unavailable, invalid, too large, or incomplete."""


class VoiceChatCancelled(VoiceChatError):
    """The caller cancelled the request."""


class _ReasoningFilter:
    """Retain partial tags so a token boundary cannot expose hidden reasoning."""

    def __init__(self) -> None:
        self.pending = ""
        self.depth = 0

    def feed(self, text: str) -> str:
        visible = []
        for char in text:
            self.pending += char
            while self.pending:
                lowered = self.pending.lower()
                if lowered == "<think>":
                    self.depth += 1
                    self.pending = ""
                elif lowered == "</think>":
                    self.depth = max(0, self.depth - 1)
                    self.pending = ""
                elif any(tag.startswith(lowered) for tag in ("<think>", "</think>")):
                    break
                else:
                    if not self.depth:
                        visible.append(self.pending[0])
                    self.pending = self.pending[1:]
        return "".join(visible)

    def finish(self) -> None:
        if self.depth or self.pending:
            raise VoiceChatError("The answer ended inside a reasoning tag.")


def _payload(messages: list[dict[str, str]], api_key: str) -> bytes:
    if not isinstance(api_key, str) or not api_key or len(api_key) > 4096 or any(
        not 33 <= ord(char) <= 126 for char in api_key
    ):
        raise VoiceChatError("A valid local gateway key is required.")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 8:
        raise VoiceChatError("Voice chat needs between one and eight messages.")
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")
                or not isinstance(message["content"], str)):
            raise VoiceChatError("Voice history must contain user and assistant text only.")
    if messages[-1]["role"] != "user" or not messages[-1]["content"].strip():
        raise VoiceChatError("Voice chat needs a final user question.")
    try:
        size = len(_SYSTEM.encode()) + sum(len(m["content"].encode("utf-8")) for m in messages)
    except UnicodeError:
        raise VoiceChatError("Voice history contains invalid text.") from None
    if size > 4096:
        raise VoiceChatError("Voice history exceeds the 4 KiB limit.")
    return json.dumps({
        "messages": [{"role": "system", "content": _SYSTEM}, *messages],
        "max_tokens": 256, "temperature": 0, "stream": True,
    }).encode("utf-8")


@contextmanager
def _response(body: bytes, api_key: str, cancel: threading.Event) -> Iterator[http.client.HTTPResponse]:
    if cancel.is_set():
        raise VoiceChatCancelled("Voice chat cancelled.")
    connection = http.client.HTTPConnection("127.0.0.1", _PORT, timeout=1)
    done, expired = threading.Event(), threading.Event()
    watcher = None
    try:
        connection.connect()
        transport = connection.sock
        if transport is None:
            raise VoiceChatError("The local chat connection did not open.")
        transport.settimeout(_TOTAL_TIMEOUT)
        deadline = time.monotonic() + _TOTAL_TIMEOUT

        def watch() -> None:
            while not done.wait(0.05):
                if cancel.is_set() or time.monotonic() >= deadline:
                    if not cancel.is_set():
                        expired.set()
                    try:
                        transport.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        # The generator may have closed the socket concurrently.
                        return
                    return

        watcher = threading.Thread(target=watch, name="voice-chat-cancel", daemon=True)
        watcher.start()
        if cancel.is_set():
            raise VoiceChatCancelled("Voice chat cancelled.")
        connection.request("POST", "/v1/chat/completions", body, {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json", "Accept": "text/event-stream",
        })
        with connection.getresponse() as response:
            if response.status != 200:
                raise VoiceChatError(f"Local chat returned HTTP {response.status}.")
            if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                raise VoiceChatError("Local chat did not return an event stream.")
            yield response
            if cancel.is_set():
                raise VoiceChatCancelled("Voice chat cancelled.")
            if expired.is_set():
                raise VoiceChatError("Local chat timed out.")
    except (OSError, http.client.HTTPException, UnicodeError, VoiceChatError):
        if cancel.is_set():
            raise VoiceChatCancelled("Voice chat cancelled.") from None
        if expired.is_set():
            raise VoiceChatError("Local chat timed out.") from None
        raise
    finally:
        done.set()
        connection.close()
        if watcher is not None:
            watcher.join(timeout=0.2)


def _events(response: http.client.HTTPResponse, cancel: threading.Event) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    pending, data, event = "", [], ""
    received = 0
    while True:
        if cancel.is_set():
            raise VoiceChatCancelled("Voice chat cancelled.")
        chunk = response.read1(4096)
        if not chunk:
            decoder.decode(b"", final=True)
            raise VoiceChatError("Local chat ended before its completion marker.")
        received += len(chunk)
        if received > _MAX_WIRE_BYTES:
            raise VoiceChatError("Local chat stream exceeded its size limit.")
        pending += decoder.decode(chunk)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            line = line.removesuffix("\r")
            if not line:
                if event == "error":
                    raise VoiceChatError("Local chat reported an error.")
                if data:
                    yield "\n".join(data)
                data, event = [], ""
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            elif line.startswith("event:"):
                event = line[6:].strip()


def _visible_deltas(events: Iterable[str]) -> Iterator[str]:
    reasoning = _ReasoningFilter()
    finished, visible, size = False, False, 0
    for event in events:
        if event == "[DONE]":
            if not finished or not visible:
                raise VoiceChatError("Local chat did not finish a visible answer.")
            reasoning.finish()
            return
        try:
            obj = json.loads(event)
        except (ValueError, RecursionError):
            raise VoiceChatError("Local chat returned malformed JSON.") from None
        if not isinstance(obj, dict) or "error" in obj:
            raise VoiceChatError("Local chat reported an invalid response.")
        choices = obj.get("choices")
        if choices == [] and "usage" in obj:
            continue
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise VoiceChatError("Local chat returned invalid choices.")
        choice = choices[0]
        delta = choice.get("delta")
        if choice.get("index", 0) != 0 or not isinstance(delta, dict) or finished:
            raise VoiceChatError("Local chat returned an invalid text delta.")
        if any(delta.get(key) is not None for key in ("tool_calls", "function_call")):
            raise VoiceChatError("Tool requests are unavailable in voice chat.")
        if delta.get("role", "assistant") != "assistant" or delta.get("refusal"):
            raise VoiceChatError("Local chat did not return an assistant answer.")
        for key in ("content", "reasoning_content", "reasoning"):
            value = delta.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise VoiceChatError("Local chat returned non-text content.")
                size += len(value.encode("utf-8"))
        if size > _MAX_TEXT_BYTES:
            raise VoiceChatError("Local chat answer exceeded the 16 KiB limit.")
        channel = delta.get("channel", choice.get("channel", "final"))
        if channel not in ("final", "analysis", "reasoning"):
            raise VoiceChatError("Local chat returned an unknown answer channel.")
        if channel == "final":
            content = reasoning.feed(delta.get("content") or "")
            if content:
                visible = visible or bool(content.strip())
                yield content
        finish = choice.get("finish_reason")
        if finish is not None:
            if finish != "stop":
                raise VoiceChatError("Local chat answer was interrupted or truncated.")
            finished = True
    raise VoiceChatError("Local chat ended before its completion marker.")


def stream_answer(messages: list[dict[str, str]], api_key: str, cancel: threading.Event) -> Iterator[str]:
    """Yield answer text; cancellation or incomplete output raises VoiceChatError.

    Close this generator when abandoning playback to release the HTTP connection.
    Text yielded before a later error is partial, never a successful full answer.
    """
    body = _payload(messages, api_key)
    try:
        with _response(body, api_key, cancel) as response:
            for content in _visible_deltas(_events(response, cancel)):
                if cancel.is_set():
                    raise VoiceChatCancelled("Voice chat cancelled.")
                yield content
    except (OSError, http.client.HTTPException, UnicodeError):
        raise VoiceChatError("The local chat connection failed.") from None


class _SpeechFilter:
    def __init__(self) -> None:
        self.fence = ""
        self.ticks = ""
        self.ansi = ""
        self.ansi_length = 0

    def feed(self, text: str) -> str:
        result = []
        for char in text:
            if self.ansi:
                self.ansi_length += 1
                if self.ansi_length > 4096:
                    raise VoiceChatError("Unterminated terminal control sequence in answer.")
                if self.ansi == "escape":
                    self.ansi = {"[": "csi", "]": "osc"}.get(char, "")
                elif self.ansi == "csi" and "@" <= char <= "~":
                    self.ansi = ""
                elif self.ansi == "osc" and char in ("\x07", "\x9c"):
                    self.ansi = ""
                elif self.ansi == "osc" and char == "\x1b":
                    self.ansi = "osc_end"
                elif self.ansi == "osc_end":
                    self.ansi = "" if char == "\\" else "osc"
                continue
            if char in ("\x1b", "\x9b", "\x9d"):
                self.ansi = {"\x1b": "escape", "\x9b": "csi", "\x9d": "osc"}[char]
                self.ansi_length = 0
                continue
            if char in ("`", "~"):
                if self.ticks and self.ticks[0] != char:
                    if not self.fence:
                        result.append(self.ticks)
                    self.ticks = ""
                self.ticks += char
                continue
            if self.ticks:
                if len(self.ticks) >= 3 and not self.fence:
                    self.fence = self.ticks
                elif (self.fence and self.ticks[0] == self.fence[0]
                      and len(self.ticks) >= len(self.fence)):
                    self.fence = ""
                    result.append(" ")
                elif not self.fence:
                    result.append(self.ticks)
                self.ticks = ""
            if self.fence:
                continue
            if char.isspace():
                result.append(" ")
            elif not unicodedata.category(char).startswith("C"):
                result.append(char)
        return "".join(result)


def sentence_chunks(parts: Iterable[str], max_chars: int = 240) -> Iterator[str]:
    """Speak bounded sentences; suppress fenced code, reasoning and ANSI controls."""
    if type(max_chars) is not int or not 16 <= max_chars <= 1000:
        raise ValueError("max_chars must be between 16 and 1000.")
    reasoning, speech = _ReasoningFilter(), _SpeechFilter()
    pending, size = "", 0
    for part in parts:
        if not isinstance(part, str):
            raise VoiceChatError("Speech input must be text.")
        size += len(part.encode("utf-8"))
        if size > _MAX_TEXT_BYTES:
            raise VoiceChatError("Speech input exceeded the 16 KiB limit.")
        for char in speech.feed(reasoning.feed(part)):
            if char == " " and (not pending or pending.endswith(" ")):
                continue
            pending += char
            if char == " " and len(pending) > 1 and pending[-2] in ".!?":
                yield pending.strip()
                pending = ""
            elif len(pending) >= max_chars:
                boundary = pending.rfind(" ")
                boundary = boundary if boundary > 0 else max_chars
                yield pending[:boundary].strip()
                pending = pending[boundary:].lstrip()
    reasoning.finish()
    if pending.strip():
        yield pending.strip()
