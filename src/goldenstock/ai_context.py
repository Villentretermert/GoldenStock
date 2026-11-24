"""Check proposed context against primary evidence and explicitly cited snippets."""
import re
from goldenstock.normalization import CURRENCIES, METRICS

POLICY = 'gs004-cited-context-v1'
SCALE_WORDS = {
    'units': r'\bunits?\b', 'thousands': r'\bthousands?\b',
    'millions': r'\bmillions?\b', 'billions': r'\bbillions?\b',
    'percent': r'%|\bpercent(?:age)?\b', 'bps': r'\bbps\b|\bbasis points?\b',
}
SCALE_ALIASES = {'unit':'units','thousand':'thousands','million':'millions','billion':'billions'}


def normalized(text):
    return ' '.join(text.split()).casefold()


def literal_in(value, texts):
    needle = normalized(value)
    if not needle:
        return False
    return any(re.search(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', normalized(text))
               for text in texts)


def currencies(texts):
    return {code for code in CURRENCIES if any(
        re.search(r'(?<!\w)' + code + r'(?!\w)', text) for text in texts)}


def validate_context(proposal, primary, cited, nearby=None):
    """Presence is necessary, never proof of semantic applicability or approval."""
    support = [primary, *cited]
    available = cited if nearby is None else nearby
    kind = METRICS[proposal.metric][1]
    if proposal.currency is not None:
        # Primary explicit currency wins; multiple codes cannot select a column.
        allowed = currencies([primary]) or currencies(available)
        if (kind != 'money' or allowed != {proposal.currency}
                or proposal.currency not in currencies(support)):
            raise ValueError('currency lacks unique explicit support')
    if proposal.scale is not None:
        # Equivalent source spellings are checked without rewriting the saved response.
        scale = SCALE_ALIASES.get(proposal.scale, proposal.scale)
        pattern = SCALE_WORDS.get(scale)
        if (pattern is None or not any(re.search(pattern, text, re.I) for text in support)
                or (kind == 'ratio' and scale not in {'units','percent','bps'})
                or (kind != 'ratio' and scale in {'percent','bps'})):
            raise ValueError('scale lacks explicit compatible support')
        if kind != 'ratio':
            def magnitudes(texts):
                return {key for key in ('units','thousands','millions','billions')
                        if any(re.search(SCALE_WORDS[key], text, re.I) for text in texts)}
            if (magnitudes([primary]) or magnitudes(available)) != {scale}:
                raise ValueError('scale lacks unique explicit support')
    for field in ('period', 'perimeter'):
        value = getattr(proposal, field)
        if value is not None and not literal_in(value, support):
            raise ValueError(field + ' is not present in cited evidence')
    if proposal.period is not None:
        def years(texts):
            return {year for text in texts for year in
                    re.findall(r'(?<!\w)(?:FY\s*)?((?:19|20)\d{2})(?!\w)', text, re.I)}
        preferred = years([primary]) or years(available)
        selected = years([proposal.period])
        if len(preferred) > 1 or (selected and preferred != selected):
            raise ValueError('period cannot select an ambiguous year or override primary evidence')
    if proposal.definition is not None and not literal_in(proposal.definition, [primary]):
        raise ValueError('definition must quote a primary metric label')
