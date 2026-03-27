import re
from bs4 import BeautifulSoup

def _validate_xpath_in_dom(xpath: str, raw_html: str) -> bool:
    """
    Returns True if the XPath resolves to at least one element in the DOM.
    Uses lxml for proper XPath 1.0 support; falls back gracefully if unavailable.
    """
    try:
        from lxml import etree  # type: ignore

        parser = etree.HTMLParser()
        tree = etree.fromstring(raw_html.encode(), parser)
        matches = tree.xpath(xpath)
        return bool(matches)

    except ImportError:
        # lxml not installed — skip validation, don't block the suggestion
        return True
    except etree.XPathEvalError:
        return False
    except Exception:
        return False
    

def _resolve_placeholders(selector: str, dom_context: str) -> tuple[str, str]:
    """
    Detects unresolved format placeholders like {!s}, {0}, {name} in the selector.
    Tries to infer the correct value from the DOM and substitutes it.

    Returns:
        (resolved_selector, note_for_llm)
    """

    # unresolved selector for run time: {!s} here s is to be filled
    placeholders = re.findall(r"\{[^}]*\}", selector)
    if not placeholders:
        return selector, ""   # nothing to fix

    # --- Infer what the placeholder represents from the XPath structure ---
    # e.g. "//div[text()='{!s}']" → the placeholder is element visible text
    # e.g. "@class='{!s}'" → the placeholder is an attribute value

    context_clue = _infer_placeholder_context(selector)

    # --- Extract candidate values from DOM that fit that context ---
    candidate_value = _extract_candidate_from_dom(dom_context, context_clue, placeholder=placeholders[0])

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

    # Could not resolve — return as-is, let LLM handle with a warning
    note = (
        f"Selector contained unresolved placeholder(s) {placeholders} "
        f"that could not be automatically resolved from the DOM. "
        f"Treat the placeholder as a wildcard when finding the intended element."
    )
    return selector, note


def _infer_placeholder_context(selector: str) -> str:
    """
    Looks at what surrounds the placeholder in the XPath to understand
    what kind of value is expected there.

    //div[text()='{!s}']                  → "visible text of a div"
    //input[@placeholder='{!s}']          → "input placeholder text"
    //div[@class='inventory_item_{!s}']   → "class name fragment"
    ancestor::div[@class='{!s}']          → "ancestor class name"
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

    return "visible text"   # safest default — most placeholders are text matches


#checkpoint
def _extract_candidate_from_dom(dom_context: str, context_clue: str, placeholder: str = "") -> str:
    """
    Extracts the most likely candidate value from the DOM
    based on what the placeholder context expects.
    """
    soup = BeautifulSoup(dom_context, "html.parser")

    if context_clue == "visible text":
        # Find all meaningful text nodes in div/span/p/button/a
        candidates = []
        for tag in soup.find_all(["div", "span", "p", "button", "a", "h1", "h2", "h3"]):
            text = tag.get_text(strip=True)
            # Meaningful: not too short, not too long, no special chars
            if 3 < len(text) < 60 and not re.search(r"[{}<>]", text):
                candidates.append(text)
            
        if not candidates:
            return ""

        # Score by similarity to placeholder key e.g. "{item_name}" → "item name"
        if placeholder:
            ph_clean = re.sub(r"[^a-z0-9]", " ", placeholder.strip("{}").lower())
            def score(text):
                return sum(word in text.lower() for word in ph_clean.split())
            candidates.sort(key=score, reverse=True)

        return candidates[0]
        # Return the first unique meaningful candidate
        # return candidates[0] if candidates else ""   # checkpoint

    if context_clue == "input placeholder text":
        tag = soup.find("input", placeholder=True)
        return tag["placeholder"] if tag else ""

    if context_clue == "aria-label":
        tag = soup.find(attrs={"aria-label": True})
        return tag["aria-label"] if tag else ""

    if context_clue == "class name":
        tag = soup.find(class_=True)
        cls = tag.get("class", [])
        return cls[0] if cls else ""

    if context_clue == "element id":
        tag = soup.find(id=True)
        return tag.get("id", "")

    return ""
