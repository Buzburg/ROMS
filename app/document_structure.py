"""Source boundaries and honest locations for extracted, normalized evidence."""
import ast
from dataclasses import dataclass, field
import re


@dataclass
class Block:
    text: str
    source: dict = field(default_factory=dict)


def text_blocks(text, suffix, notes):
    """Split Markdown sections and Python definitions without executing input."""
    boundaries = [(0, {})]
    lines = text.splitlines(keepends=True)
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    if suffix in {'.md', '.markdown'}:
        headings, fence = [], None
        for line, offset in zip(lines, offsets):
            marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
            if marker:
                run = marker[1]
                if fence is None:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence):
                    fence = None
                continue
            heading = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
            if heading and fence is None:
                level = len(heading[1])
                headings = [(depth, name) for depth, name in headings if depth < level]
                headings.append((level, heading[2][:256]))
                boundaries.append((offset, {'section_path': [name for _, name in headings]}))
    elif suffix == '.py':
        try:
            tree = ast.parse(text)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    line = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                    boundaries.append((offsets[line - 1], {'symbol': node.name}))
        except (SyntaxError, ValueError, RecursionError):
            notes.append('Python syntax could not be parsed; original text retained without guessed symbols')
    # A heading/definition at offset zero replaces the anonymous initial block.
    boundaries = sorted(dict(boundaries).items())
    blocks = []
    for index, (start, source) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(text)
        if text[start:end].strip():
            blocks.append(Block(text[start:end], {**source, 'parent_id': f'section:{index}',
                'offset_basis': 'normalized_text', 'start_char': start, 'end_char': end,
                'line_start': text.count('\n', 0, start) + 1}))
    return blocks


def slice_source(source, text, start, end):
    """Offsets describe normalized text or a named extracted block, never bytes."""
    result = dict(source)
    base = source.get('start_char', 0)
    result.update(start_char=base + start, end_char=base + end)
    if 'line_start' in source:
        result['line_start'] = source['line_start'] + text.count('\n', 0, start)
        result['line_end'] = source['line_start'] + text.count('\n', 0, max(start, end - 1))
    return result


def split_blocks(blocks, splitter):
    chunks, sources = [], []
    for index, block in enumerate(blocks):
        meta = {'block_id': f'block:{index}', 'parent_id': f'block:{index}', 'offset_basis': 'extracted_block', **block.source}
        position = 0
        for piece in splitter(block.text):
            start = block.text.find(piece, position)
            if start < 0:
                raise ValueError('Passage splitter changed source evidence')
            chunks.append(piece)
            sources.append(slice_source(meta, block.text, start, start + len(piece)))
            position = start + len(piece)
            if len(chunks) > 20000:
                raise ValueError('Document exceeds the 20,000 passage limit')
    return chunks, sources


def embedding_header(title, source):
    fields = [f'Document: {title[:256]}']
    if source.get('section_path'):
        fields.append('Section: ' + ' > '.join(source['section_path'])[:512])
    if source.get('symbol'):
        fields.append('Symbol: ' + source['symbol'])
    if source.get('columns'):
        fields.append('Columns: ' + ', '.join(source['columns'])[:512])
    if source.get('page') is not None:
        fields.append(f"Page: {source['page']}")
    return '\n'.join(fields) + '\n\n'
