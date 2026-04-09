import json
import re
import textwrap
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from ...config import get_api_key, get_base_url, get_model_name, get_temperature

_SYSTEM_PROMPT = textwrap.dedent("""
    You are an expert in web automation and XPath.
    Your job is to repair a broken XPath selector that no longer finds its
    intended element in the current DOM, because the UI has changed.

    You will be given:
      1. The FAILED selector (XPath or CSS) and, optionally, the error message.
      2. A compact summary of interactive elements currently in the DOM.
                                 
    If failure_mode is "timing":
    - The XPath may still be correct. Focus on whether wait_strategy should be "explicit_wait".
    If failure_mode is "unstable_attr":
    - The element exists but its class/id rotated. Anchor to aria-label, data-testid, or text.
    If failure_mode is "structure_changed":
    - The DOM tree restructured. Use ancestor/following-sibling axes relative to stable text.

    Your task — think step by step:
      A. INTENT: What was the failed selector *meant* to do?
         (e.g. "click the primary login button", "fill the search field")
      B. IDENTIFY: Which element in the current DOM is now fulfilling that
         same intent, even if its text, class, or ID changed?
         Consider: text content, aria-label, surrounding form/parent context,
         data-testid, type, placement clues.
      C. SUGGEST: Write the single best XPath for that element.
         Prefer, in order: data-testid > aria-label > stable text > name attr.
         Avoid fragile positional XPaths like [1] unless nothing else exists.
      D. REASON: Explain in 1-3 sentences why you chose this element and XPath.
      E. CONFIDENCE: Rate your confidence as "high", "medium", or "low".

                         
    You MUST respond with ONLY valid JSON — no markdown, no extra text:
    {
      "intent":     "<what the original selector was meant to do>",
      "xpath":      "<your suggested XPath>",
      "reason":     "<your explanation>",
      "confidence": "high" | "medium" | "low",
      "stability":     "stable" | "medium" | "fragile",
      "wait_strategy": "none" | "explicit_wait" | "poll"
    }

    If you genuinely cannot identify a matching element, return:
    {
      "intent":     "<inferred intent>",
      "xpath":      null,
      "reason":     "<why you could not find a match>",
      "confidence": "low"
      "stability":     "stable" | "medium" | "fragile",
      "wait_strategy": "none" | "explicit_wait" | "poll"
    }
    
""").strip()

def _invoke_llm(
    failed_selector: str,
    dom_summary: str,
    error_msg: str,
    failure_mode,
    extra_context: str = "",    
) -> dict:
    """Calls the LLM to reason about intent and generate a healed XPath.""" 

    user_message = textwrap.dedent(f"""
        FAILED SELECTOR: {failed_selector}

        ERROR (if any):
        {error_msg or "No error message provided."}

        Type of failure:
        {failure_mode}

        {f"ADDITIONAL CONTEXT:{chr(10)}{extra_context}" if extra_context else ""}

        CURRENT DOM (interactive elements summary):
        {dom_summary}
    """).strip()

    try:
        llm = ChatOpenAI(
            model=get_model_name(),
            base_url=get_base_url(),
            api_key=get_api_key(),
            temperature=get_temperature(),
            max_tokens=1024,
            timeout=30,
            max_retries=2,
        )

        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])

        raw_text = response.content.strip()

        # Strip accidental markdown fences
        raw_text_strip = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.DOTALL).strip()

        result = json.loads(raw_text_strip)

        # Normalise — ensure required keys exist
        return {
            "intent":     result.get("intent", "Unknown intent"),
            "xpath":      result.get("xpath"),           # None is valid (no match)
            "reason":     result.get("reason", ""),
            "confidence": result.get("confidence", "low"),
            "stability": result.get("stability", "unknown"),
            "wait_strategy": result.get("wait_strategy", "unknown")
        }

    except json.JSONDecodeError as exc:
        return {
            "intent":     "Parse error",
            "xpath":      None,
            "reason":     f"LLM returned non-JSON output: {exc}",
            "confidence": "low",
        }
    except Exception as exc:                  # covers all Groq / OpenAI / network errors
        return {
            "intent":     "API error",
            "xpath":      None,
            "reason":     f"Groq API error: {exc}",
            "confidence": "low",
        }
