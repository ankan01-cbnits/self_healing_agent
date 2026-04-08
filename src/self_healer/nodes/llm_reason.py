import json
import re
from langchain_core.messages import HumanMessage, SystemMessage
from self_healer.prompts import llm_agent_prompts
from ..state import AgentState
from ..config import get_api_key, get_base_url, get_model_name, get_temperature
from langchain_openai import ChatOpenAI


def _get_llm():
    """Lazy-initialise the LLM so env vars are read at call time, not import time."""
    return ChatOpenAI(
        model=get_model_name(),
        base_url=get_base_url(),
        api_key=get_api_key(),
        temperature=get_temperature(),
    )


def reason_and_suggest(state: AgentState) -> dict:
    messages = state.get("messages", [])
    new_messages = []
    
    if not messages:
        is_xpath = state.get("is_xpath", False)
        xpath_candidates = state.get("xpath_candidates") or []

        # 1. Select the System Prompt
        sys_content = llm_agent_prompts.XPATH_REPAIR_SYSTEM_PROMPT if is_xpath else llm_agent_prompts.STATIC_SITE_SYSTEM_PROMPT
        sys_prompt = SystemMessage(content=sys_content)

        # 2. Build the XPath Candidate Section
        xpath_section = ""
        if xpath_candidates:
            ranked = "\n".join(f"  {i+1}. {x}" for i, x in enumerate(xpath_candidates))
            xpath_section = f"\nXPath Candidates (pre-computed, ranked by stability):\n{ranked}\n"

        # 3. Build the Human Task Prompt
        if is_xpath:
            task_content = (
                f"Test Name : {state['test_name']}\n"
                f"Selector  : {state['selector']}\n"
                f"Error     : {state['error']}\n"
                f"xpath     : {state['suggestion']}\n"
                f"confidence : {state['confidence']}\n"
                f"reason    : {state['reason']}\n"
                f"intent    : {state.get('intent', 'Unknown')}\n"
                f"{xpath_section}"
            )
        else:
            task_content = (
                f"Test Name : {state['test_name']}\n"
                f"Selector  : {state['selector']}\n"
                f"Error     : {state['error']}\n"
                f"DOM       : {state['dom_context']}\n"
                # f"{xpath_section}"
            )
        
        task_prompt = HumanMessage(content=task_content)
        messages = [sys_prompt, task_prompt]
        new_messages.extend(messages)

    llm = _get_llm()
    response = llm.invoke(messages)
    new_messages.append(response)

    # print("RESPONSE CONTENT: ", response.content)
    
    parsed = _parse_llm_output(response.content)

    # print("What is going: ", parsed)
    suggestion = parsed.get("suggestion")
    reason = parsed.get("reason")
    confidence = parsed.get("confidence")

    state["suggestion"] = suggestion
    state["confidence"] = confidence
    state["reason"] = reason
    state["messages"] = new_messages
    # print("=== what is going ===")
    # print(f"xpath      : {state['suggestion']} : {suggestion}")
    # print(f"confidence : {state['confidence']} : {confidence}")
    # print(f"reason     : {state['reason']}: {reason}")
    return state

def _parse_llm_output(content: str) -> dict:
    try:
        # Extract JSON using regex to avoid conversational text
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            clean = match.group(0)
        else:
            clean = content.strip().replace("```json", "").replace("```", "").strip()
            
        parsed = json.loads(clean)

        # Handle the LLM returning a list for "suggestion" or "selector"
        suggestion = parsed.get("suggestion") or parsed.get("selector")
        if isinstance(suggestion, list) and len(suggestion) > 0:
            suggestion = suggestion[0]
        elif not suggestion:
            suggestion = "No suggestion available"

        # Normalize confidence, handling percentages or strings
        conf_raw = parsed.get("confidence", 0.0)
        if isinstance(conf_raw, str):
            conf_raw = conf_raw.replace('%', '').strip()
            try:
                conf = float(conf_raw)
            except ValueError:
                conf = 0.0
        else:
            try:
                conf = float(conf_raw)
            except (ValueError, TypeError):
                conf = 0.0

        return {
            "suggestion": suggestion,
            "reason":     parsed.get("reason") or "No reason provided",
            "confidence": conf,
            "intent":     parsed.get("intent", "Unknown")
        }

    except (json.JSONDecodeError, ValueError):
        return {
            "suggestion": "Failed to parse LLM output",
            "reason":     "The LLM response was not valid JSON",
            "confidence": 0.0,
            "intent":     "Unknown"
        }