from bs4 import BeautifulSoup
from langgraph.graph import StateGraph, START, END
from .nodes.dom_extractor import dom_extractor
from .nodes.llm_reason import reason_and_suggest
from .nodes.file_locator import file_locator
from .nodes.human_approval import human_approval
from .nodes.apply_fix import apply_fix
from .nodes.xpath_builder import xpath_builder
from .state import AgentState

def route_by_selector_type(state: AgentState):
    return "xpath" if state.get("is_xpath") else "Dom_Extractor"

def route_after_reasoning(state: AgentState):
    """
    After reason_and_suggest:
    - If confidence is low AND retries remaining → go back to xpath_builder
    - If confidence is low AND retries exhausted → go to Human_Approval directly
    - If confidence is good enough              → proceed to File_Locator
    """
    confidence  = state.get("confidence", 0.0)
    retry_count = state.get("retry_count", 0)
    is_xpath    = state.get("is_xpath", False)

    if confidence < 50.0:
        if is_xpath and retry_count < 2:
            return "xpath"            # retry xpath_builder
        return "Human_Approval"       # exhausted or CSS — escalate

    return "File_Locator"             # confident enough, proceed


def check_approval(state: AgentState):
    if state.get("approved"):
        return "Apply_Fix"
    return END


builder = StateGraph(AgentState)

# Add nodes
builder.add_node("Dom_Extractor", dom_extractor)
builder.add_node("Reasoning_agent", reason_and_suggest)
builder.add_node("File_Locator", file_locator)
builder.add_node("Human_Approval", human_approval)
builder.add_node("Apply_Fix", apply_fix)
builder.add_node("xpath", xpath_builder)

# Set flow
builder.add_conditional_edges(START,
                              route_by_selector_type, 
    {
        "Dom_Extractor": "Dom_Extractor",
        "xpath": "xpath",
    })

builder.add_edge("xpath", "Reasoning_agent")
builder.add_edge("Dom_Extractor", "Reasoning_agent")
builder.add_conditional_edges("Reasoning_agent", route_after_reasoning, {
    "xpath":          "xpath",           # low confidence retry
    "Human_Approval": "Human_Approval",  # low confidence, exhausted
    "File_Locator":   "File_Locator",    # confident, proceed
})
builder.add_edge("File_Locator", "Human_Approval")

builder.add_conditional_edges("Human_Approval", 
    check_approval, 
    {
        "Apply_Fix": "Apply_Fix",
        END: END
    }
)
builder.add_edge("Apply_Fix", END)

self_healing_graph = builder.compile()

def graph_init():
    return self_healing_graph