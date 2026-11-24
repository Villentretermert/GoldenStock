"""Bind proposed numbers to whole source tokens, including sign and percent."""
import re

NUMBER_VALIDATION_VERSION = 'gs004-whole-number-v1'

# Keep a separated sign, accounting parentheses and percent with their number.
# Unsupported/malformed spellings are later rejected by normalization.number.
NUMBER_TOKEN = re.compile(
    r'(?<![\w.])(?:\(\s*)?(?:[+\-−]\s*)?\d[\d,]*(?:\.\d+)?'
    r'(?:\s*%)?(?:\s*\))?(?![\w]|\.\d)'
)


def numeric_tokens(text):
    return {match.group() for match in NUMBER_TOKEN.finditer(text)}


def quoted_number_supported(source, quote, token):
    """Require one exact quote occurrence containing the entire source token.

    Checking token membership in the quote alone misses quotes cut through a
    larger number. Matching only the whole source misses numbers outside it.
    """
    spans = [(match.start(), match.end()) for match in NUMBER_TOKEN.finditer(source)
             if match.group() == token]
    if not spans or not quote:
        return False
    offset = source.find(quote)
    while offset != -1:
        end = offset + len(quote)
        if any(offset <= left and right <= end for left, right in spans):
            return True
        offset = source.find(quote, offset + 1)
    return False
