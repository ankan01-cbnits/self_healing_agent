from lxml import etree
import re

# Fix 1 — Extended to include structurally-container tags needed for nesting output
INTERACTIVE_TAGS = {
    "a", "button", "input", "select", "textarea",
    "form", "label", "nav", "header", "main", "section"
}

# Fix 1 — Attributes that make a non-interactive tag behaviorally interactive
BEHAVIORAL_ATTRS = {"onclick", "onchange", "onsubmit", "onkeydown", "onkeyup"}
BEHAVIORAL_ROLES = {"button", "link", "menuitem", "tab", "checkbox", "radio", "option", "switch"}

_MAX_ELEMENTS = 60
_MAX_ATTR_VALUE_LEN = 50

PRIORITY_ATTRS = [
    "data-testid", "data-cy", "aria-label", "id",
    "name", "type", "role", "placeholder", "href", "class"
]


# ─────────────────────────────────────────────
# Fix 1 — Behavioral tag check
# ─────────────────────────────────────────────

def _is_interactive(el) -> bool:
    """
    Returns True if element is interactive either by tag or by behavior.
    Catches React/Vue patterns like:
      <div role="button" onclick="...">
      <li data-testid="menu-item">
      <span aria-label="close" role="button">
    """
    if el.tag in INTERACTIVE_TAGS:
        return True
    # role-based: <div role="button">
    if el.get("role") in BEHAVIORAL_ROLES:
        return True
    # event-handler-based: <div onclick="...">
    if any(el.get(attr) for attr in BEHAVIORAL_ATTRS):
        return True
    # test-id-based: <li data-testid="..."> — explicit test hooks are always targets
    if el.get("data-testid") or el.get("data-cy"):
        return True
    return False


# ─────────────────────────────────────────────
# Fix 2 — Nested (indented) output
# ─────────────────────────────────────────────

def _summarise_dom(raw_html: str, failed_selector: str = "") -> str:
    """
    Produces a compact, nested DOM summary anchored to the failure site.

    Fixes applied:
      1. Behavioral tag detection (role, onclick, data-testid on any tag)
      2. Nested indented output preserving parent-child relationships
      4. Retry with wider anchor if target element is beyond the 60-element cap
      5. Sibling context: includes siblings of the deepest resolved ancestor
    """
    try:
        parser = etree.HTMLParser()
        tree = etree.fromstring(raw_html.encode(), parser)
    except Exception:
        return "<empty/>"

    anchor = _find_anchor_node(tree, failed_selector)

    # Fix 4 — If we hit the cap, retry with the anchor's parent (wider window)
    result = _render_nested(anchor)
    if result.strip().endswith(f"... truncated after {_MAX_ELEMENTS} elements ..."):
        parent = anchor.getparent()
        if parent is not None:
            result = _render_nested(parent, retry=True)

    return result if result.strip() else "<empty/>"


def _render_nested(root, retry: bool = False) -> str:
    """
    Walks the subtree and emits indented lines reflecting DOM depth.
    Only interactive elements are emitted, but their nesting depth
    relative to the anchor root is preserved so the LLM sees structure.

    Fix 5 — Also renders siblings of root so positional XPaths are possible.
    """
    root_depth = sum(1 for _ in root.iterancestors())
    lines: list[str] = []
    count = [0]  # mutable for nested helper
    cap = _MAX_ELEMENTS if not retry else _MAX_ELEMENTS * 2  # Fix 4 — wider on retry

    # Fix 5 — Include siblings by starting from parent's children
    parent = root.getparent()
    scope = list(parent) if parent is not None else [root]

    def _walk(el, depth: int):
        if count[0] >= cap:
            lines.append(" " * depth + f"... truncated after {cap} elements ...")
            return

        if _is_interactive(el):
            indent = "  " * depth
            lines.append(indent + _format_element_lxml(el, open_tag_only=True))
            count[0] += 1

        for child in el:
            _walk(child, depth + 1)

        # Close tag only if element had interactive children (keeps output readable)
        if _is_interactive(el):
            has_interactive_children = any(_is_interactive(c) for c in el.iter() if c is not el)
            if has_interactive_children:
                indent = "  " * depth
                lines.append(indent + f"</{el.tag}>")

    for sibling in scope:
        rel_depth = sum(1 for _ in sibling.iterancestors()) - root_depth
        _walk(sibling, max(rel_depth, 0))

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Anchor finding (unchanged logic, kept intact)
# ─────────────────────────────────────────────

def _find_anchor_node(tree, failed_selector: str):
    body = tree.find(".//body") or tree

    if not failed_selector:
        return body

    ancestor = _resolve_closest_ancestor(tree, failed_selector)
    if ancestor is not None:
        return ancestor

    keywords = _extract_keywords(failed_selector)
    if keywords:
        landmark = _find_landmark(tree, keywords)
        if landmark is not None:
            return landmark

    return body


def _resolve_closest_ancestor(tree, xpath: str):
    parts = re.split(r'(?=//|/(?!/))', xpath)
    parts = [p for p in parts if p]

    for end in range(len(parts), 0, -1):
        candidate = "".join(parts[:end])
        if len(candidate.strip("/")) < 2:
            continue
        try:
            results = tree.xpath(candidate)
            if results:
                return results[0]
        except etree.XPathEvalError:
            continue
    return None


def _extract_keywords(selector: str) -> list[str]:
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", selector)
    words: list[str] = []
    for q in quoted:
        words.append(q)
        words.extend(re.split(r"[-_\s]+", q))
    words += re.findall(r'/(\w+)', selector)
    return [w.lower() for w in words if len(w) > 2]


def _find_landmark(tree, keywords: list[str]):
    LANDMARK_TAGS = {"form", "section", "main", "nav", "header", "div", "article"}
    best: tuple[int, any] | None = None

    for el in tree.iter():
        if el.tag not in LANDMARK_TAGS:
            continue
        attrs = " ".join([
            el.get("id", ""),
            " ".join(el.get("class", "").split()),
            el.get("role", ""),
            el.get("aria-label", ""),
        ]).lower()
        if any(kw in attrs for kw in keywords):
            depth = sum(1 for _ in el.iterancestors())
            if best is None or depth > best[0]:
                best = (depth, el)

    return best[1] if best else None


# ─────────────────────────────────────────────
# Formatter
# ─────────────────────────────────────────────

def _format_element_lxml(el, open_tag_only: bool = False) -> str:
    """
    Fix 2 — Added open_tag_only mode for nested rendering.
    When True, returns just the opening tag (closing handled by _render_nested).
    """
    parts = []
    seen: set[str] = set()
    for attr in PRIORITY_ATTRS + list(el.attrib.keys()):
        if attr in seen:
            continue
        seen.add(attr)
        val = el.get(attr)
        if val is None:
            continue
        val_str = val.replace("\n", " ").strip()
        if len(val_str) > _MAX_ATTR_VALUE_LEN:
            val_str = val_str[:_MAX_ATTR_VALUE_LEN] + "..."
        parts.append(f'{attr}="{val_str}"')
    attrs_str = (" " + " ".join(parts)) if parts else ""

    direct_text = (el.text or "").strip()[:60]
    tag = el.tag

    if open_tag_only:
        # Fix 2 — Nesting mode: emit open tag with inline text if present
        if direct_text:
            return f"<{tag}{attrs_str}>{direct_text}"
        return f"<{tag}{attrs_str}>"

    # Original flat mode (kept for backward compatibility)
    if direct_text:
        return f"<{tag}{attrs_str}>{direct_text}</{tag}>"
    return f"<{tag}{attrs_str} />"


# ─────────────────────────────────────────────
# _classify_failure — wired to reasoning agent externally
# ─────────────────────────────────────────────

def _classify_failure(error_msg: str) -> str:
    if any(k in error_msg.lower() for k in ["timeout", "not found", "stale"]):
        return "timing"
    if any(k in error_msg.lower() for k in ["no such element", "unable to locate"]):
        return "structure_changed"
    return "unstable_attr"