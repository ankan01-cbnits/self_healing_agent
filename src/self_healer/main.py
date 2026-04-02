from bs4 import BeautifulSoup

from .graph import graph_init


def run_healing_agent(test_name: str, selector: str, error: str, page) -> None:
    dom_context = page.content()
    
    def is_xpath_selector(sel: str) -> bool:
        s = sel.strip()
        return (
            s.startswith("/") or
            s.startswith("//") or
            s.lower().startswith("xpath=")
        )
    is_xpath = is_xpath_selector(selector)

    state = {
        "test_name":   test_name,
        "selector":    selector,
        "error":       error,
        "dom_context": dom_context,
        "suggestion":  None,
        "confidence":  0.0,
        "reason":      None,
        "step_passed": False,
        "messages":    [],
        "approved":    False,
        "file_path":   None,
        "line_number": None,
        "is_xpath":  is_xpath,
        "wait_strategy": "",
        "failure_mode": "",
        "retry_count": 0
    }

    # Step 1 — LangGraph runs on current thread (inside Playwright's event loop)
    graph  = graph_init()
    graph.invoke(state)