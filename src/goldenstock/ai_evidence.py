"""Bounded, lossless source windows for explicit analyst-triggered AI requests."""
import json

SELECTION_VERSION = 'gs028-source-window-v1'
MAX_EVIDENCE_JSON = 6000


def source_window(items, version_id, source_sha256, offset=0, text_offset=0):
    if not 0 <= offset < len(items):
        raise ValueError('Evidence item not found')
    raw = items[offset].get('text') or ''
    if not 0 <= text_offset <= len(raw) or (text_offset == len(raw) and raw):
        raise ValueError('Text position is outside this evidence item')
    if text_offset and not raw[text_offset - 1].isspace():
        raise ValueError('Text position must follow whitespace to preserve whole tokens')
    evidence = []
    cursor = None
    for index in range(offset, min(offset + 8, len(items))):
        item = items[index]
        text = item.get('text') or ''
        start = text_offset if index == offset else 0
        cursor = dict(offset=index + 1, text_offset=0) if index + 1 < len(items) else None
        if not text[start:].strip():
            continue

        def entry(end):
            return dict(id=f'{version_id}:{index}', text=text[start:end],
                        location=item['location'], source_sha256=source_sha256,
                        item_index=index, source_range=[start, end], source_length=len(text))

        def fits(end):
            return len(json.dumps(evidence + [entry(end)], ensure_ascii=True)) <= MAX_EVIDENCE_JSON

        end = len(text)
        if not fits(end):
            if evidence:
                cursor = dict(offset=index, text_offset=start)
                break
            # Binary search counts JSON escaping, including non-BMP Unicode characters.
            low, high = start, end
            while low < high:
                mid = (low + high + 1) // 2
                if fits(mid):
                    low = mid
                else:
                    high = mid - 1
            end = low
            # Prefer a complete line. Never cut a non-whitespace token in half.
            newline = text.rfind('\n', start, end)
            if newline >= start + (end - start) // 2:
                end = newline + 1
            else:
                while end > start and not text[end - 1].isspace():
                    end -= 1
            if end == start or not text[start:end].strip():
                raise ValueError('A source token exceeds the AI limit; review this item manually')
        evidence.append(entry(end))
        if end < len(text):
            cursor = dict(offset=index, text_offset=end)
            break
    return dict(evidence=evidence, selection_version=SELECTION_VERSION,
                offset=offset, text_offset=text_offset, next_cursor=cursor)
