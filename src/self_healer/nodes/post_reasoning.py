import re
import logging
from self_healer.state import AgentState

logger = logging.getLogger(__name__)

def post_reasoning_processor(state: AgentState) -> dict:
    confidence = state.get("confidence", 0.0)

    if confidence >= 50.0:
        cleaned = _unresolve_placeholders(
            broken_selector=state["selector"],
            fixed_selector=state["suggestion"]
        )
        return {"suggestion": cleaned}

    return {}

def _unresolve_placeholders(
    broken_selector: str,
    fixed_selector: str,
) -> str:
    """
    Reverses placeholder resolution on a structurally different fixed XPath.
    Returns the fixed XPath with concrete values replaced back to their
    placeholder tokens from the broken selector.

    Args:
        broken_selector : original failing XPath, may contain {!s}, {0}, {name} etc.
        fixed_selector  : healed XPath produced by the LLM / agent.

    Returns:
        unresolved_fixed_selector (str)

    Example:
        broken  : //button[@data-test='add-to-cart-{!s}']
        fixed   : //div[descendant::div[text()='Sauce Labs Backpack']]/...
        returns : //div[descendant::div[text()='{!s}']]/...
    """
    placeholders = re.findall(r"\{[^}]*\}", broken_selector)
    if not placeholders:
        return fixed_selector

    segments = re.split(r"(\{[^}]*\})", broken_selector)

    pattern_parts: list[str] = []
    ordered_placeholders: list[str] = []

    for seg in segments:
        if re.fullmatch(r"\{[^}]*\}", seg):
            ordered_placeholders.append(seg)
            pattern_parts.append(r"(.+?)")
        else:
            pattern_parts.append(re.escape(seg))

    broken_pattern = "".join(pattern_parts)
    ph_to_value: dict[str, str] = {}

    try:
        match = re.search(broken_pattern, fixed_selector, re.DOTALL)
        if match:
            for ph, captured in zip(ordered_placeholders, match.groups()):
                ph_to_value[ph] = captured
    except re.error as exc:
        logger.warning("_unresolve_placeholders: regex match failed: %s", exc)

    # Fallback: use delimiter context around the placeholder
    for ph in ordered_placeholders:
        if ph in ph_to_value:
            continue

        ph_escaped = re.escape(ph)
        ctx_match = re.search(
            r"(['\"\-_/]?)(?:" + ph_escaped + r")(['\"\-_/\]\)]?)",
            broken_selector,
        )
        if not ctx_match:
            logger.warning("Could not find context around placeholder %r", ph)
            continue

        left_delim  = re.escape(ctx_match.group(1))
        right_delim = re.escape(ctx_match.group(2))

        val_match = re.search(left_delim + r"(.+?)" + right_delim, fixed_selector)
        if val_match:
            ph_to_value[ph] = val_match.group(1)

    if not ph_to_value:
        logger.warning("_unresolve_placeholders: could not extract any resolved values.")
        return fixed_selector

    unresolved = fixed_selector
    for ph, value in ph_to_value.items():
        if value and value in unresolved:
            unresolved = unresolved.replace(value, ph)
        else:
            logger.warning(
                "_unresolve_placeholders: value %r for placeholder %r not found in fixed XPath",
                value, ph,
            )

    return unresolved
