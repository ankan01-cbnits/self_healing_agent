from bs4 import BeautifulSoup
from ..state import AgentState
from ..utils.dom.dom_utils import build_selector_hints, climb_to_container, safe_serialize
from ..utils.dom.fingerprints import find_by_fingerprint, infer_fingerprint_from_selector
from ..utils.dom.selector_resolver import resolve_from_error, resolve_playwright_selector

def dom_extractor(state: AgentState) -> dict:
    selector    = state["selector"]
    error       = state["error"]
    dom_context = state["dom_context"]

    soup = BeautifulSoup(dom_context, 'html.parser')

    node = resolve_playwright_selector(soup, selector)
    if node is None:
        node = resolve_from_error(soup, error)
    if node is None:
        fingerprint = infer_fingerprint_from_selector(selector)
        node = find_by_fingerprint(soup, fingerprint)

    if node:
        container = climb_to_container(node, max_levels=4)
        focused_dom = safe_serialize(container, char_limit=5000)
    else:
        focused_dom = safe_serialize(soup.body, char_limit=3000)

    hints = build_selector_hints(soup, selector)
    
    return {
        "dom_context": focused_dom + hints,
        }
