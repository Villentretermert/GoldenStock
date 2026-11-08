"""Source-derived financial headings and bounded nearby context, without inference."""
import hashlib
import json
import re

SECTION_POLICY = 'gs030-source-headings-v1'
CONTEXT_POLICY = 'gs030-nearby-context-v1'
CONTEXT_BUDGET = 2200
# Exact whole lines avoid treating a TOC entry or narrative reference as a heading.
HEADING = re.compile(
    r'(?:(?:condensed |consolidated |combined |group |company |interim )*)'
    r'(?:balance sheets?|income statements?|statements? of (?:income|operations|'
    r'comprehensive income|financial position|cash flows?|changes in (?:equity|stockholders[’\']? equity|shareholders[’\']? equity))|'
    r'financial (?:statements|highlights|review|summary)|risk management|capital management|'
    r'notes to (?:the )?(?:consolidated )?financial statements|'
    r'management[’\']?s discussion and analysis|operating and financial review)'
    r'(?:\s*\(continued\))?', re.I)


def source_lines(items):
    """Keep every title/context character linked to the original extraction item."""
    lines = []
    words = {}
    for index, item in enumerate(items):
        loc = item.get('location', {})
        if not loc.get('page'):
            continue
        text = item.get('text') or ''
        if item.get('method') == 'ocr' and item.get('kind') == 'word':
            key = (loc['page'], loc.get('block'), loc.get('paragraph'), loc.get('line'))
            words.setdefault(key, []).append((index, item))
        elif item.get('kind', 'text') == 'text':
            offset = 0
            for raw in text.splitlines(keepends=True):
                start = offset + len(raw) - len(raw.lstrip())
                end = offset + len(raw.rstrip())
                if start < end:
                    lines.append(dict(text=text[start:end], page=loc['page'], method='native',
                        sources=[dict(item_index=index, source_range=[start, end], location=loc)]))
                offset += len(raw)
    for group in words.values():
        # OCR line membership and word order come from the parser, never from an AI guess.
        group.sort(key=lambda x: (x[1]['location'].get('word', 0), x[0]))
        lines.append(dict(text=' '.join(x['text'] for _, x in group),
            page=group[0][1]['location']['page'], method='ocr',
            sources=[dict(item_index=i, source_range=[0, len(x['text'])], location=x['location']) for i, x in group]))
    return sorted(lines, key=lambda x: (x['page'], x['sources'][0]['item_index'], x['sources'][0]['source_range'][0]))


def context_entry(line, version_id, source_hash, role):
    key = json.dumps(line['sources'], sort_keys=True)
    return dict(id='ctx-' + hashlib.sha256((version_id + key).encode()).hexdigest()[:24],
        text=line['text'], page=line['page'], method=line['method'], role=role,
        version_id=version_id, source_sha256=source_hash, sources=line['sources'])


def sections(lines, version_id, source_hash, total_pages):
    found = []; seen = set()
    for line in lines:
        title = ' '.join(line['text'].split())
        key = (line['page'], title.casefold())
        if len(title) > 160 or not HEADING.fullmatch(title) or key in seen:
            continue
        seen.add(key)
        entry = context_entry(line, version_id, source_hash, 'heading')
        found.append(dict(id=entry['id'], title=line['text'], page_start=line['page'],
            heading=entry, boundary_status='inferred_from_next_heading'))
        if len(found) > 500:
            raise ValueError('Too many heading candidates; select original pages instead')
    for index, item in enumerate(found):
        next_page = found[index+1]['page_start'] if index+1 < len(found) else total_pages+1
        item['page_end'] = max(item['page_start'], next_page-1)
        item['same_page_headings'] = sum(s['page_start']==item['page_start'] for s in found) > 1
    return found


def nearby_context(window, lines, version_id, source_hash, section=None):
    evidence = window['evidence']
    first = min((e['location']['page'], e['item_index'], e['source_range'][0]) for e in evidence)
    last = max((e['location']['page'], e['item_index'], e['source_range'][1]) for e in evidence)
    candidates = []
    if section:
        candidates.append(section['heading'])
    # A page heading and its following line often carry scale/year information.
    low=max(first[0]-1,section['page_start']) if section else first[0]-1
    high=min(last[0]+1,section['page_end']) if section else last[0]+1
    near = [x for x in lines if low <= x['page'] <= high]
    headings=[(pos,line) for pos,line in enumerate(near)
        if HEADING.fullmatch(' '.join(line['text'].split())) and first[0]-1 <= line['page'] <= first[0]
        and (line['sources'][0]['item_index'],line['sources'][0]['source_range'][0])
            <= (evidence[0]['item_index'],evidence[0]['source_range'][1])]
    if headings:
        pos,line=headings[-1]
        candidates.append(context_entry(line, version_id, source_hash, 'heading'))
        if pos+1 < len(near) and near[pos+1]['page'] == line['page']:
            candidates.append(context_entry(near[pos+1], version_id, source_hash, 'heading_following_line'))
    before = [x for x in near if (x['page'], x['sources'][-1]['item_index'], x['sources'][-1]['source_range'][1]) <= first]
    after = [x for x in near if (x['page'], x['sources'][0]['item_index'], x['sources'][0]['source_range'][0]) >= last]
    for line in before[-2:] + after[:2]:
        candidates.append(context_entry(line, version_id, source_hash, 'adjacent_line'))
    result = []; seen = set(); omitted = 0
    for entry in candidates:
        if entry['id'] in seen:
            continue
        seen.add(entry['id'])
        # Keep context distinct, but do not send a second copy of text already in the primary input.
        if all(any(e['item_index']==s['item_index'] and e['source_range'][0]<=s['source_range'][0]
                   and e['source_range'][1]>=s['source_range'][1] for e in evidence) for s in entry['sources']):
            continue
        if len(entry['text']) > 600 or len(entry['sources']) > 32 or len(json.dumps(result+[entry])) > CONTEXT_BUDGET:
            omitted += 1
            continue
        result.append(entry)
    return dict(context=result, context_omitted=omitted, context_policy=CONTEXT_POLICY)
