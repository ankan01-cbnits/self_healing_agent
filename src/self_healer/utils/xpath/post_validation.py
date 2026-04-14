import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _validate_xpath_in_dom(xpath: str, raw_html: str) -> bool:
    """
    Returns True if the XPath resolves to at least one element in the DOM.

    Step 1 — Try lxml for proper XPath 1.0 support.
    Step 2 — Catch XPathSyntaxError and XPathEvalError separately.
    Step 3 — Log unexpected errors instead of silently swallowing them.
    """
    try:
        from lxml import etree # type: ignore

        parser = etree.HTMLParser()
        tree = etree.fromstring(raw_html.encode(), parser)
        matches = tree.xpath(xpath)
        return bool(matches)

    except ImportError:
        # lxml not installed — skip validation, don't block the suggestion
        return True
    except etree.XPathSyntaxError as exc:
        # Step 2 — malformed XPath string (e.g. unclosed bracket)
        logger.warning("XPath syntax error for %r: %s", xpath, exc)
        return False
    except etree.XPathEvalError as exc:
        # Step 2 — valid syntax but evaluation failed (e.g. bad axis)
        logger.warning("XPath eval error for %r: %s", xpath, exc)
        return False
    except Exception as exc:
        # Step 3 — unexpected error, log it so it is not silently lost
        logger.error("Unexpected error validating XPath %r: %s", xpath, exc)
        return False


def _resolve_placeholders(selector: str, dom_context: str) -> tuple[str, str]:
    """
    Detects unresolved format placeholders like {!s}, {0}, {name} in the selector.
    Tries to infer the correct value from the DOM and substitutes it.

    Returns:
        (resolved_selector, note_for_llm)
    """
    placeholders = re.findall(r"\{[^}]*\}", selector)
    if not placeholders:
        return selector, ""

    context_clue = _infer_placeholder_context(selector)

    # Step — extract target tag from selector to narrow DOM search
    target_tag = _extract_target_tag(selector)

    candidate_value = _extract_candidate_from_dom(
        dom_context, context_clue, target_tag
    )

    if candidate_value:
        resolved = selector
        for ph in placeholders:
            resolved = resolved.replace(ph, candidate_value)

        note = (
            f"Selector contained unresolved placeholder(s) {placeholders}. "
            f"Inferred context: '{context_clue}'. "
            f"Substituted with DOM candidate: '{candidate_value}'."
        )
        return resolved, note

    note = (
        f"Selector contained unresolved placeholder(s) {placeholders} "
        f"that could not be automatically resolved from the DOM. "
        f"Treat the placeholder as a wildcard when finding the intended element."
    )
    return selector, note


def _extract_target_tag(selector: str) -> str | None:
    """
    Extracts the target HTML tag from the XPath selector.

    //button[@aria-label=...]  →  "button"
    //input[@placeholder=...]  →  "input"
    //div[text()=...]          →  "div"
    Returns None if no tag can be inferred.
    """
    match = re.search(r"//(\w+)\[", selector)
    return match.group(1) if match else None


def _infer_placeholder_context(selector: str) -> str:
    """
    Looks at what surrounds the placeholder in the XPath to understand
    what kind of value is expected there.

    //div[text()='{!s}']                  → "visible text"
    //input[@placeholder='{!s}']          → "input placeholder text"
    //div[@class='inventory_item_{!s}']   → "class name"
    ancestor::div[@class='{!s}']          → "class name"
    """
    patterns = [
        (r"text\(\)\s*=\s*['\"][^'\"]*\{[^}]*\}[^'\"]*['\"]",     "visible text"),
        (r"@placeholder\s*=\s*['\"][^'\"]*\{[^}]*\}[^'\"]*['\"]", "input placeholder text"),
        (r"@aria-label\s*=\s*['\"][^'\"]*\{[^}]*\}[^'\"]*['\"]",  "aria-label"),
        (r"@class\s*=\s*['\"][^'\"]*\{[^}]*\}[^'\"]*['\"]",       "class name"),
        (r"@id\s*=\s*['\"][^'\"]*\{[^}]*\}[^'\"]*['\"]",          "element id"),
        (r"@name\s*=\s*['\"][^'\"]*\{[^}]*\}[^'\"]*['\"]",        "input name"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, selector, re.IGNORECASE):
            return label

    return "visible text"


def _extract_candidate_from_dom(
    dom_context: str,
    context_clue: str,
    target_tag: str | None = None,
) -> str:
    """
    Extracts the most likely candidate value from the DOM based on context.

    Fix applied: now filters by target_tag extracted from the selector,
    so we don't return the first random div text from the whole page.
    Falls back to broad search if target_tag is None or yields no results.
    """
    soup = BeautifulSoup(dom_context, "html.parser")

    if context_clue == "visible text":
        # Narrow search to the target tag first, fall back to common tags
        search_tags = (
            [target_tag]
            if target_tag
            else ["div", "span", "button", "a", "h1", "h2", "h3", "p"]
        )
        for tag in soup.find_all(search_tags):
            text = "".join(
                s for s in tag.strings if s.parent == tag
            ).strip()
            # Meaningful: not too short, not too long, no special chars
            if 3 < len(text) < 60 and not re.search(r"[{}<>]", text):
                return text
        return ""

    if context_clue == "input placeholder text":
        search = soup.find(target_tag or "input", placeholder=True)
        return search["placeholder"] if search else ""

    if context_clue == "aria-label":
        search = soup.find(target_tag or True, attrs={"aria-label": True})
        return search["aria-label"] if search else ""

    if context_clue == "class name":
        search = soup.find(target_tag or True, class_=True)
        cls = search.get("class", []) if search else []
        return cls[0] if cls else ""

    if context_clue == "element id":
        search = soup.find(target_tag or True, id=True)
        return search.get("id", "") if search else ""

    if context_clue == "input name":
        search = soup.find(target_tag or "input", attrs={"name": True})
        return search.get("name", "") if search else ""

    return ""
