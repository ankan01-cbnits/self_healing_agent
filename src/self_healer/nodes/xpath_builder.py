"""
xpath_builder.py — Self-Healing Agent Node
==========================================
Invoked when an XPath selector fails to resolve an element in the live DOM.

Responsibilities:
  1. Understand the *semantic intent* of the failed XPath (what action was it
     meant to perform, e.g. "click the login button").
  2. Search the current DOM for the element now fulfilling that intent, even
     if its tag, text, or attributes have changed.
  3. Produce a single best XPath suggestion and a plain-English reason, then
     update state["xpath_suggestion"].

State keys consumed:
  - state["selector"]     : the original XPath / CSS selector that failed
  - state["dom_context"]  : raw HTML of the current page / component
  - state["error"]        : (optional) error message from the previous attempt
  - state["is_xpath"]   : bool — skip healing on static pages

State keys produced:
  - state["suggestion"]: "xpath"  : str  — the suggested replacement XPath
  - state["reason]: "reason" : str  — plain-English explanation of the reasoning
  - state["confident"]: "confidence": "high" | "medium" | "low"
  - state["intent"]: intent: what is suppose to do
    On failure / skip: {"xpath": None, "reason": "<why>", "confidence": "low"}
"""

# from bs4 import BeautifulSoup
from ..state import AgentState
from ..utils.xpath.dom_summarisation import _summarise_dom, _classify_failure
from ..utils.xpath.llm_wrapper import _invoke_llm
from ..utils.xpath.post_validation import _resolve_placeholders, _validate_xpath_in_dom

# ---------------------------------------------------------------------------
# Public agent-node entry point
# ---------------------------------------------------------------------------

def xpath_builder(state: AgentState) -> dict:
    """LangGraph / custom-graph node.  Returns a partial state patch."""

    selector: str = state.get("selector", "")
    dom_context: str = state.get("dom_context", "")
    error_msg: str = state.get("error", "")

    if not selector or not dom_context:    
        state["suggestion"]=None
        state["resone"]="Missing selector or DOM context; cannot attempt healing."
        state["intent"]=None
        state["confidence"]="low"

    # --- Step 1: distil the DOM to a lean, LLM-friendly summary -------------
    dom_summary = _summarise_dom(dom_context, selector)

    # --- Resolve unresolved template placeholders before anything else ---
    selector, placeholder_note = _resolve_placeholders(selector, dom_context)

    #classify what is wrong
    state["failure_mode"]=_classify_failure(error_msg=state["error"])

    # --- Step 2: call the LLM to reason about intent + suggest XPath --------
    suggestions = _invoke_llm(
        failed_selector=selector,
        dom_summary=dom_summary,
        error_msg=error_msg,
        failure_mode = state["failure_mode"],
        extra_context=placeholder_note
    )

    # print("=== XPATH_BUILDER OUTPUT ===")
    # print(f"xpath      : {suggestions.get('xpath')}")
    # print(f"confidence : {suggestions.get('confidence')}")
    # print(f"reason     : {suggestions.get('reason')}")
    # print(f"intent     : {suggestions.get('intent')}")
    # print("============================")

    # --- Step 3: validate the suggested XPath against the live DOM ----------
    if suggestions["xpath"]:
        valid = _validate_xpath_in_dom(suggestions["xpath"], dom_context)
        if not valid:
            suggestions["reason"] += (
                " (Note: the suggested XPath could not be verified against the "
                "current DOM snapshot — please double-check before use.)"
            )
            suggestions["confidence"] = "low"

    # confidence string → float conversion for AgentState compatibility
    confidence_map = {"high": 90.0, "medium": 60.0, "low": 20.0}
    raw_conf = suggestions.get("confidence", "low")
    confidence_float = confidence_map.get(raw_conf.lower(), 0.0) if isinstance(raw_conf, str) else float(raw_conf)

    state['suggestion']=suggestions.get("xpath")
    state['confidence']=confidence_float
    state['reason']=suggestions.get("reason")
    state['intent']=suggestions.get("intent")
    state["retry_count"] = state.get("retry_count", 0) + 1

    # print("=== XPATH_BUILDER OUTPUT ===")
    # print(f"xpath      : {state['suggestion']}")
    # print(f"confidence : {state['confidence']}")
    # print(f"reason     : {state['reason']}")
    # print(f"intent     : {state['intent']}")
    # print("============================")

    return state
