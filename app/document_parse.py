"""Recover searchable text without executing files or silently discarding broken records."""
import csv
from dataclasses import dataclass
from html.parser import HTMLParser
import io
import json
from pathlib import Path

import frontmatter
import yaml
from app.search_native import kernels

PARSER_VERSION = 'messy-v1'
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CHUNKS = 20000


@dataclass
class ParsedDocument:
    title: str
    kind: str
    raw: bytes
    text: str
    chunks: list[str]
    encoding: str
    notes: list[str]


def read_text(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('Document exceeds the 32 MiB ingestion limit')
    if raw.startswith((b'%PDF-', b'PK\x03\x04', b'\x89PNG', b'\xff\xd8\xff', b'\x7fELF', b'\x1f\x8b')):
        raise ValueError('Binary document requires a format-specific extractor; text was not indexed')
    notes = []
    if raw.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        encoding = 'utf-32'
    elif raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        encoding = 'utf-16'
    elif len(raw) >= 8 and raw[1::2].count(0) > len(raw) * .2:
        encoding = 'utf-16-le'
        notes.append('Inferred UTF-16 little-endian encoding without a BOM')
    elif len(raw) >= 8 and raw[::2].count(0) > len(raw) * .2:
        encoding = 'utf-16-be'
        notes.append('Inferred UTF-16 big-endian encoding without a BOM')
    else:
        if raw.count(0) > max(2, len(raw) // 100):
            raise ValueError('Binary-looking data is not supported by the text importer')
        try:
            raw.decode('utf-8-sig')
            encoding = 'utf-8-sig'
        except UnicodeDecodeError:
            encoding = 'cp1252'
            notes.append('Invalid UTF-8; decoded as Windows-1252')
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode(encoding, errors='replace')
        notes.append('Undecodable bytes replaced with the Unicode replacement character')
    cleaned = kernels().clean(text)
    if cleaned != text:
        notes.append('Normalized line endings, nonbreaking spaces, BOMs or control characters')
    return raw, cleaned, encoding, notes


def _metadata(value, default, name, notes):
    if isinstance(value, str) and value.strip() and len(value) <= 4096:
        return value.strip()
    if value is not None:
        notes.append(f'Invalid {name} metadata; using filename/default')
    return default


def _markdown(path, text, notes):
    try:
        post = frontmatter.loads(text)
        title = _metadata(post.metadata.get('title'), path.name, 'title', notes)
        kind = _metadata(post.metadata.get('type'), 'general', 'type', notes)
        body = post.content.strip()
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        title, kind, body = path.name, 'general', text
        notes.append('Malformed frontmatter preserved as text')
    return title, kind, body, [body]


def _csv(path, text, notes):
    nonblank = text.lstrip('\n')
    delimiter = '\t' if path.suffix.lower() == '.tsv' else ','
    try:
        delimiter = csv.Sniffer().sniff(nonblank[:8192], delimiters=',;\t|').delimiter
    except csv.Error:
        # Ragged rows often defeat Sniffer; a header-only sniff is still quote-aware.
        try:
            delimiter = csv.Sniffer().sniff(nonblank.splitlines()[0], delimiters=',;\t|').delimiter
        except (csv.Error, IndexError):
            pass
    try:
        rows = [row for row in csv.reader(io.StringIO(nonblank), delimiter=delimiter, strict=True) if any(row)]
    except csv.Error:
        notes.append('Malformed CSV quoting preserved as raw text')
        return path.name, 'tabular', text, [text]
    if not rows:
        return path.name, 'tabular', text, []
    headers = rows.pop(0)
    width = max([len(headers), *map(len, rows)])
    if any(len(row) != len(headers) for row in rows):
        notes.append('Uneven CSV rows: extra columns retained and missing cells marked')
    unique, seen = [], set()
    for i in range(width):
        base = headers[i].strip() if i < len(headers) else ''
        base = base or f'Column_{i+1}'
        label = base
        while label in seen:
            label += f'_{i+1}'
        seen.add(label)
        unique.append(label)
    chunks = []
    heading = f'Table: {path.name}\nColumns: ' + ', '.join(unique)
    for i in range(0, len(rows), 5):
        records = []
        for j, row in enumerate(rows[i:i+5], i+1):
            values = [f'{key}: {row[k] if k < len(row) else "[missing cell]"}' for k, key in enumerate(unique)]
            records.append(f'Row {j}: ' + '; '.join(values))
        chunks.append(heading + '\n' + '\n'.join(records))
    return f'Dataset: {path.name}', 'tabular', text, chunks or [heading]


def _json(path, text, notes):
    title = f'Structured Data: {path.name}'
    if path.suffix.lower() in {'.jsonl', '.ndjson'}:
        chunks, group = [], []
        invalid = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except (ValueError, RecursionError):
                if len(invalid) < 20:
                    invalid.append(number)
            group.append(f'Line {number}: {line}')
            if len(group) == 3:
                chunks.append('\n'.join(group)); group = []
        if group:
            chunks.append('\n'.join(group))
        if invalid:
            notes.append(f'Malformed JSONL lines retained as text (first 20): {invalid}')
        return title, 'json_dataset', text, chunks
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            chunks = [f'{key}: {json.dumps(value, ensure_ascii=False)}' for key, value in data.items()]
        elif isinstance(data, list):
            chunks = [json.dumps(data[i:i+3], ensure_ascii=False) for i in range(0, len(data), 3)]
        else:
            chunks = [text]
    except (ValueError, RecursionError):
        notes.append('Malformed JSON retained as raw text; no guessed repairs')
        chunks = [text]
    return title, 'json_dataset', text, chunks or [text]


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        elif not self.hidden and tag in {'p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append(' ')
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def parse_document(path):
    path = Path(path)
    from app.document_extract import BINARY_EXTENSIONS, extract_document
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        with path.open('rb') as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('Document exceeds the 32 MiB ingestion limit')
        title, kind, chunks, notes = extract_document(path, raw)
        bounded = []
        for chunk in chunks:
            bounded.extend(kernels().passages(kernels().clean(chunk)))
            if len(bounded) > MAX_CHUNKS:
                raise ValueError('Document exceeds the passage limit')
        return ParsedDocument(title, kind, raw, '\n\n'.join(bounded), bounded, 'binary/extracted', notes)
    raw, text, encoding, notes = read_text(path)
    if suffix in {'.md', '.markdown'}:
        title, kind, text, chunks = _markdown(path, text, notes)
    elif suffix in {'.csv', '.tsv'}:
        title, kind, text, chunks = _csv(path, text, notes)
    elif suffix in {'.json', '.jsonl', '.ndjson'}:
        title, kind, text, chunks = _json(path, text, notes)
    elif suffix in {'.html', '.htm'}:
        parser = _HTMLText(); parser.feed(text)
        visible = ''.join(parser.parts).strip()
        title, kind, chunks = path.name, 'text', [visible or text]
    else:
        title = f'Source: {path.name}'
        kind = 'code' if suffix in {'.py', '.mojo', '.sql', '.sh', '.ps1', '.ts', '.js', '.rs', '.go', '.c', '.cpp', '.tsx', '.jsx'} else 'text'
        chunks = [text]
    bounded = []
    for chunk in chunks:
        bounded.extend(kernels().passages(chunk))
        if len(bounded) > MAX_CHUNKS:
            raise ValueError('Document exceeds the 20,000 passage limit')
    return ParsedDocument(title, kind, raw, text, bounded, encoding, notes)


def fit_model_window(chunks, model):
    """Split by actual tokenizer offsets so even dense Unicode text cannot truncate."""
    tokenizer = getattr(model, 'tokenizer', None)
    if tokenizer is None:
        return chunks  # deterministic test doubles / providers without a tokenizer
    budget = int(model.max_seq_length) - tokenizer.num_special_tokens_to_add(pair=False)
    if budget < 8:
        raise ValueError('Embedding model has an unusable context window')
    fitted = []
    for chunk in chunks:
        tokens = tokenizer(chunk, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
        offsets = tokens['offset_mapping']
        if len(offsets) <= budget:
            fitted.append(chunk)
            if len(fitted) > MAX_CHUNKS:
                raise ValueError('Document exceeds the model passage limit')
            continue
        start = 0
        while start < len(offsets):
            end = min(start + budget, len(offsets))
            left = 0 if start == 0 else offsets[start][0]
            right = len(chunk) if end == len(offsets) else offsets[end][0]
            # A substring beginning inside a word can tokenize differently.
            piece = chunk[left:right]
            while len(tokenizer(piece, add_special_tokens=False)['input_ids']) > budget:
                end -= 1
                if end <= start:
                    raise ValueError('Tokenizer cannot produce a bounded passage')
                right = offsets[end][0]
                piece = chunk[left:right]
            fitted.append(piece)
            if end == len(offsets):
                break
            start = max(start + 1, end - min(24, budget // 4))
        if len(fitted) > MAX_CHUNKS:
            raise ValueError('Document exceeds the model passage limit')
    return fitted
