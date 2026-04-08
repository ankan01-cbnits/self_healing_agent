from langgraph.graph import StateGraph, START, END
from .nodes.dom_extractor import dom_extractor
from .nodes.llm_reason import reason_and_suggest
from .nodes.file_locator import file_locator
from .nodes.human_approval import human_approval
from .nodes.apply_fix import apply_fix
from .nodes.xpath_builder import xpath_builder
from .nodes.rerun_engine import TestRerunEngine
from .state import AgentState


def route_by_selector_type(state: AgentState):
    return "xpath" if state.get("is_xpath") else "Dom_Extractor"


def route_after_reasoning(state: AgentState):
    confidence  = state.get("confidence", 0.0)
    retry_count = state.get("retry_count", 0)
    is_xpath    = state.get("is_xpath", False)

    if confidence < 50.0:
        if is_xpath and retry_count < 2:
            return "xpath"
        return "Human_Approval"

    return "File_Locator"


def check_approval(state: AgentState):
    if state.get("approved"):
        return "Apply_Fix"
    return END


def route_after_fix(state: AgentState):
    """
    After apply_fix + rerun:
      rerun passed              → done, all consecutive tests passed too
      rerun failed + cycles left → reset and re-heal with fresh LLM attempt
      rerun failed + exhausted  → stop
    """
    if state.get("rerun_passed", True):
        return END

    heal_cycles = state.get("heal_cycles", 0)
    if heal_cycles >= TestRerunEngine.MAX_HEAL_CYCLES:
        print(f"\n[agent] Max heal cycles ({TestRerunEngine.MAX_HEAL_CYCLES}) reached. Stopping.")
        return END

    # Reset conversational state for a fresh healing attempt
    state["messages"]    = []
    state["suggestion"]  = None
    state["approved"]    = False
    state["retry_count"] = 0

    return "xpath" if state.get("is_xpath") else "Dom_Extractor"


builder = StateGraph(AgentState)

builder.add_node("Dom_Extractor",   dom_extractor)
builder.add_node("Reasoning_agent", reason_and_suggest)
builder.add_node("File_Locator",    file_locator)
builder.add_node("Human_Approval",  human_approval)
builder.add_node("Apply_Fix",       apply_fix)
builder.add_node("xpath",           xpath_builder)

builder.add_conditional_edges(
    START,
    route_by_selector_type,
    {"Dom_Extractor": "Dom_Extractor", "xpath": "xpath"},
)

builder.add_edge("xpath",         "Reasoning_agent")
builder.add_edge("Dom_Extractor", "Reasoning_agent")

builder.add_conditional_edges(
    "Reasoning_agent",
    route_after_reasoning,
    {
        "xpath":          "xpath",
        "Human_Approval": "Human_Approval",
        "File_Locator":   "File_Locator",
    },
)

builder.add_edge("File_Locator", "Human_Approval")

builder.add_conditional_edges(
    "Human_Approval",
    check_approval,
    {"Apply_Fix": "Apply_Fix", END: END},
)

builder.add_conditional_edges(
    "Apply_Fix",
    route_after_fix,
    {END: END, "Dom_Extractor": "Dom_Extractor", "xpath": "xpath"},
)

self_healing_graph = builder.compile()


def graph_init():
    return self_healing_graph