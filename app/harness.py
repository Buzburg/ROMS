"""Prepare bounded evidence and an advisory decision without executing a tool."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any

from app import config
from app.decisions import ROMSDecisionEngine
from app.json_protocol import unique_object
from app.safe_paths import markdown_path


def decode_request(raw: str) -> dict:
    """Decode the same bounded, unambiguous request for CLI and MCP callers."""
    if type(raw) is not str:
        raise ValueError('Request JSON must be UTF-8 text')
    try:
        if len(raw.encode('utf-8')) > 32768:
            raise ValueError('Request JSON exceeds 32 KiB')
    except UnicodeError as error:
        raise ValueError('Request JSON must be valid UTF-8 text') from error

    def reject_constant(value: str) -> None:
        raise ValueError('Non-finite JSON values are not accepted: ' + value)

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            reject_constant(value)
        return number

    try:
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_float)
    except (RecursionError, UnicodeError) as error:
        raise ValueError('Invalid or excessively nested request JSON') from error
    if type(value) is not dict:
        raise ValueError('Request JSON must contain an object')
    return value


def _text(value: Any, name: str, maximum: int, *, required: bool = True) -> str:
    if type(value) is not str or len(value) > maximum or '\x00' in value or (required and not value.strip()):
        raise ValueError(f'{name} must be text up to {maximum} characters' + (' and not empty' if required else ''))
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise ValueError(f'{name} must be valid UTF-8 text') from error
    return value


def _request(value: dict) -> dict:
    allowed = {'goal', 'options', 'evidence', 'skills', 'max_context_chars'}
    if type(value) is not dict or set(value) - allowed or not {'goal', 'options'} <= set(value):
        raise ValueError('Request requires goal and options; optional fields are evidence, skills and max_context_chars')
    goal = _text(value['goal'], 'goal', 2048)
    options = value['options']
    if type(options) is not dict or not 2 <= len(options) <= 10:
        raise ValueError('options must contain 2..10 named descriptions')
    for key, description in options.items():
        if type(key) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', key):
            raise ValueError('Option IDs must be 1..64 letters, digits, underscores or hyphens')
        _text(description, 'option description', 512)
    skills = value.get('skills', [])
    if type(skills) is not list or len(skills) > 4:
        raise ValueError('skills must be a list of up to four Markdown leaf names')
    for skill in skills:
        _text(skill, 'skill name', 128)
    budget = value.get('max_context_chars', 6000)
    if type(budget) is not int or not 512 <= budget <= 16000:
        raise ValueError('max_context_chars must be an integer from 512 to 16000')
    return {'goal': goal, 'options': dict(options), 'evidence': _text(value.get('evidence', ''), 'evidence', 4000, required=False),
            'skills': list(skills), 'max_context_chars': budget}


def _digest(text: str | bytes) -> str:
    return hashlib.sha256(text.encode('utf-8') if isinstance(text, str) else text).hexdigest()


def _knowledge(goal: str, database: Path) -> dict:
    if not database.exists():
        return {'status': 'unavailable', 'reason': 'No existing knowledge database was found; no database was created.', 'sources': []}
    if not database.is_file():
        raise ValueError('Knowledge database must be an existing regular file')
    connection = None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 256 * 1024)
        ticks = 0

        def bounded_query() -> int:
            nonlocal ticks
            ticks += 1
            return int(ticks > 5000)

        connection.set_progress_handler(bounded_query, 1000)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        for table, required in {'fts_chunks': {'chunk_id', 'doc_id', 'content'},
                                'okf_registry': {'doc_id', 'title', 'checksum'}}.items():
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            if not required <= columns:
                raise ValueError('Knowledge database is missing the required ROMS FTS/OKF schema')
        try:
            from app.rag_engine import lexical_search
        except ImportError as error:
            raise ValueError('Knowledge retrieval requires the existing ROMS RAG dependencies; no installation was attempted') from error
        sources = []
        for found in lexical_search(goal, limit=3, conn=connection):
            doc_id = _text(found.get('doc_id'), 'indexed source identifier', 4096)
            content = _text(found.get('content'), 'indexed source content', 256 * 1024, required=False)
            metadata = connection.execute('SELECT title, checksum FROM okf_registry WHERE doc_id = ?', (doc_id,)).fetchone()
            if metadata is None:
                raise ValueError('Knowledge result has no matching OKF registration')
            title = _text(metadata[0], 'indexed source title', 4096, required=False)
            checksum = metadata[1]
            if type(checksum) is not str or not re.fullmatch(r'[a-fA-F0-9]{64}', checksum):
                raise ValueError('Knowledge source has an invalid stored OKF checksum')
            sources.append({'source_id': doc_id, 'title': title, 'index_checksum': checksum,
                            'indexed_chunk_sha256': _digest(content), 'excerpt': content,
                            'source_file_validated': False})
        return {'status': 'retrieved' if sources else 'no-matches', 'method': 'existing ROMS lexical_search / SQLite FTS5',
                'scope': 'Indexed snapshot; original source files were not opened or revalidated.', 'sources': sources}
    except sqlite3.Error as error:
        raise ValueError('Knowledge database could not be read as a bounded ROMS FTS/OKF snapshot: ' + str(error)) from error
    finally:
        if connection is not None:
            connection.close()


def _skills(names: list[str], directory: Path) -> list[dict]:
    if not names:
        return []
    root = directory.expanduser().absolute()
    try:
        for component in (root, *root.parents):
            info = component.lstat()
            if (not stat.S_ISDIR(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise ValueError('Skills directory must be an existing directory without linked components')
        # Windows may expand an ordinary 8.3 path spelling here. Inspect links
        # above using filesystem metadata rather than comparing path strings.
        root = root.resolve(strict=True)
    except OSError as error:
        raise ValueError('Skills directory could not be read as an existing unlinked directory') from error
    output, seen = [], set()
    for name in names:
        path = markdown_path(root, name)
        identity = path.name.casefold()
        if identity in seen:
            raise ValueError('Requested skill names resolve to the same file')
        seen.add(identity)
        try:
            before = path.lstat()
            if (not stat.S_ISREG(before.st_mode)
                    or getattr(before, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise ValueError('Skill must be a regular Markdown file')
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or path.resolve().parent != root:
                    raise ValueError('Skill changed while it was opened')
                raw = stream.read(32 * 1024 + 1)
                after = os.fstat(stream.fileno())
            if len(raw) > 32 * 1024:
                raise ValueError('Skill exceeds the 32 KiB input limit')
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Skill changed while it was read')
            content = raw.decode('utf-8')
            if '\x00' in content:
                raise ValueError('Skill must contain UTF-8 text without NUL')
        except (OSError, UnicodeError) as error:
            raise ValueError('Skill could not be read as a local UTF-8 Markdown file: ' + path.name) from error
        output.append({'name': path.name, 'source_id': 'skills://' + path.stem,
                       'sha256': _digest(raw), 'content': content, 'authority': 'untrusted_playbook_text'})
    return output


def prepare_request(request: dict, *, db_path=None, skills_dir=None) -> dict[str, Any]:
    """Collect context and heuristic advice; never execute or authorize its suggestion."""
    value = _request(request)
    database = Path(config.DB_PATH if db_path is None else db_path).expanduser()
    knowledge = _knowledge(value['goal'], database)
    skills = _skills(value['skills'], Path(config.SKILLS_DIR if skills_dir is None else skills_dir))
    remaining = value['max_context_chars']
    omitted = []
    truncated = []

    def excerpt(content: str, source_id: str) -> str:
        nonlocal remaining
        selected = content[:remaining]
        remaining -= len(selected)
        if len(selected) < len(content):
            truncated.append(source_id)
            if not selected:
                omitted.append(source_id)
        return selected

    observed = {'text': excerpt(value['evidence'], 'supplied-evidence'), 'sha256': _digest(value['evidence']),
                'authority': 'unverified_user_supplied_observations'}
    observed['truncated'] = len(observed['text']) < len(value['evidence'])
    for source in knowledge['sources']:
        original = source['excerpt']
        source['excerpt'] = excerpt(original, source['source_id'])
        source['snippet_sha256'] = _digest(source['excerpt'])
        source['truncated'] = len(source['excerpt']) < len(original)
    for skill in skills:
        original = skill['content']
        skill['content'] = excerpt(original, skill['source_id'])
        skill['truncated'] = len(skill['content']) < len(original)
    texts = [observed['text'], *(source['excerpt'] for source in knowledge['sources'])]
    state = '\n'.join(text for text in texts if text.strip())
    engine = ROMSDecisionEngine(persist_discovery=False)
    decision = engine.decide_choice(state=state, question=value['goal'], options=value['options'])
    has_evidence = bool(state.strip())
    if not has_evidence:
        decision['abstained'] = True
        decision['abstention_reasons'] = list(dict.fromkeys([*decision.get('abstention_reasons', []), 'evidence_missing']))
    abstained = decision['abstained']
    return {'schema': 'roms.harness/v1', 'status': 'abstained' if abstained else 'review-required',
            'goal': value['goal'], 'decision': decision,
            'proposed_next_step': None if abstained else value['options'][decision['choice']],
            'context': {'evidence': observed, 'knowledge': knowledge, 'skills': skills,
                        'coverage': {'max_context_chars': value['max_context_chars'],
                                     'supplied_text_chars': value['max_context_chars'] - remaining,
                                     'truncated': bool(truncated), 'truncated_sources': truncated,
                                     'omitted_sources': omitted,
                                     'scope': 'Budget covers supplied observations, retrieved excerpts and skill text; goals, choices and metadata are separate.'}},
            'backend': {'decision': 'ROMS Decision Maker', 'method': 'lexical_heuristic',
                        'model_called': False, 'probabilities_calibrated': False, 'discovery_persisted': False},
            'execution_allowed': False, 'approval_required': True,
            'notes': ['Skill instructions are separate context and do not influence decision scores.',
                      'No tool was invoked and no suggestion grants permission to act.',
                      'Knowledge queries are read-only; SQLite may use coordination sidecars for a live WAL index.']}
