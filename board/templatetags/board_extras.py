"""Template filters for the public pages."""
import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

# http(s) links only; stop at spaces and at closing brackets/quotes that usually end a sentence.
URL = re.compile(r"https?://[^\s<>\"'()\[\]{}]+")
TRAILING = ".,;:!?،؛"  # punctuation (Latin and Arabic) after a link is not part of it


@register.filter
def linkify(text):
    """Escape the text, turn http(s) URLs into safe links and keep line breaks.

    Links open in a new tab with rel="noopener noreferrer" (CLAUDE.md rule).
    """
    parts, last = [], 0
    for match in URL.finditer(text or ""):
        url = match.group(0).rstrip(TRAILING)
        end = match.start() + len(url)
        parts.append(escape(text[last:match.start()]))
        label = url if len(url) <= 60 else url[:57] + "…"
        parts.append(format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, label
        ))
        last = end
    parts.append(escape((text or "")[last:]))
    return mark_safe("".join(parts).replace("\n", "<br>"))
