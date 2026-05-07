"""
glossary_filter.py — ShutterLeague Auto-Glossary Filter
========================================================
Session 7

Registers a Jinja2 filter `autolink_glossary` that scans a text/HTML
string and wraps Tier 1 jargon terms with the correct anchor tag.

INSTALL (in app.py, near where you create the Flask app):

    from glossary_filter import register_glossary_filter
    register_glossary_filter(app)

USAGE in templates (use only on trusted/internal strings, NOT user input):

    {{ some_description | autolink_glossary }}
    {{ some_description | autolink_glossary(dark=True) }}

SAFETY:
  - Already-linked terms (inside <a …>) are NOT double-linked.
  - HTML tags are not altered — only bare text nodes.
  - Use Markup() so Jinja2 doesn't double-escape the output.
  - Never apply to user-supplied content (XSS risk).

TERM ORDER:
  Longer/more-specific phrases are matched BEFORE shorter abbreviations
  so "Apex DDI Engine" is linked before "DDI", and
  "Aesthetic Quality" before "AQ", etc.
"""

import re
from markupsafe import Markup, escape

# ---------------------------------------------------------------------------
# Registry — ordered longest-first so specific phrases win over abbreviations
# ---------------------------------------------------------------------------
GLOSSARY = [
    # term,                  href,                    abbrev_also?
    ("Apex DDI Engine",      "/science",              False),
    ("Annual Excellence Award", "/poty",              False),
    ("Depth of Detail",      "/science#dimensions",   False),
    ("Decisive Moment",      "/science#dimensions",   False),
    ("Aesthetic Quality",    "/science#dimensions",   False),
    ("Visual Disruption",    "/science#dimensions",   False),
    ("Body of Work",         "/bow_info",             False),
    ("Weekly Challenge",     "/programmes",           False),
    ("Open Programme",       "/programmes",           False),
    ("Shadow [Rr]ank",       "/how-it-works",         False),  # regex
    ("Peer [Rr]ating",       "/how-it-works",         False),  # regex
    ("Wonder",               "/science#dimensions",   False),
    ("Disruption",           "/science#dimensions",   False),
    ("DDI",                  "/science",              True),
    ("DoD",                  "/science#dimensions",   True),
    ("DM",                   "/science#dimensions",   True),
    ("AQ",                   "/science#dimensions",   True),
    ("POTY",                 "/poty",                 True),
    # "Tier" is intentionally last — very common word, only match as whole word
    ("Tier",                 "/how-it-works",         False),
]


def _build_pattern(term: str) -> re.Pattern:
    """Compile a whole-word pattern for a term (term may already be a regex)."""
    # If term doesn't already contain regex metacharacters other than []
    # treat it as a literal, otherwise use as-is
    if not any(c in term for c in r"[]().*+?^${}|\\"):
        term = re.escape(term)
    return re.compile(r"(?<![>\w])(" + term + r")(?![<\w])", re.UNICODE)


# Precompile patterns once at import time
_COMPILED = [(pat := _build_pattern(t), href, pat) for t, href, _ in GLOSSARY]
# Rebuild cleanly
_COMPILED = []
for term, href, _ in GLOSSARY:
    pat = _build_pattern(term)
    _COMPILED.append((pat, href))


def autolink_glossary(text: str, dark: bool = False) -> Markup:
    """
    Jinja2 filter. Wraps Tier 1 glossary terms in <a> tags.

    Args:
        text: Raw string (HTML ok, but avoid user-generated content).
        dark: If True, apply gold link class; if False, slate blue.

    Returns:
        Markup (safe for Jinja2 | safe rendering).
    """
    if not text:
        return Markup("")

    css_class = "glossary-link glossary-link--dark" if dark else "glossary-link glossary-link--light"

    # We need to avoid re-linking terms inside existing <a> tags.
    # Strategy: split on HTML tags, process only text nodes.
    # Simple approach: split on < > boundaries.
    parts = re.split(r"(<[^>]+>)", str(text))

    result_parts = []
    inside_anchor = False

    for part in parts:
        if part.startswith("<"):
            # It's an HTML tag
            if re.match(r"<a[\s>]", part, re.IGNORECASE):
                inside_anchor = True
            elif re.match(r"</a>", part, re.IGNORECASE):
                inside_anchor = False
            result_parts.append(part)
        else:
            # It's a text node
            if inside_anchor:
                result_parts.append(part)
            else:
                # Apply glossary linking — process each pattern sequentially.
                # After a match is made, the replacement contains HTML tags,
                # so we re-split and only process remaining bare text nodes.
                node = _apply_patterns(part, _COMPILED, css_class)
                result_parts.append(node)

    return Markup("".join(result_parts))


def _apply_patterns(text: str, compiled: list, css_class: str) -> str:
    """
    Apply each pattern in order, but after each substitution re-split on
    newly created <a> tags so later patterns can't match inside them.
    """
    for pattern, href in compiled:
        # Re-split on HTML boundaries after every pattern pass
        parts = re.split(r"(<[^>]+>)", text)
        new_parts = []
        inside = False
        for part in parts:
            if part.startswith("<"):
                if re.match(r"<a[\s>]", part, re.IGNORECASE):
                    inside = True
                elif re.match(r"</a>", part, re.IGNORECASE):
                    inside = False
                new_parts.append(part)
            else:
                if inside:
                    new_parts.append(part)
                else:
                    new_parts.append(
                        pattern.sub(
                            lambda m, h=href, c=css_class: (
                                f'<a href="{h}" class="{c}">{m.group(0)}</a>'
                            ),
                            part,
                        )
                    )
        text = "".join(new_parts)
    return text


def register_glossary_filter(app):
    """
    Register the filter with a Flask app.

    Usage in app.py:
        from glossary_filter import register_glossary_filter
        register_glossary_filter(app)

    Then in templates:
        {{ paragraph_text | autolink_glossary }}
        {{ paragraph_text | autolink_glossary(dark=True) }}
    """
    app.jinja_env.filters["autolink_glossary"] = autolink_glossary
