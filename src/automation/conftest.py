import re
import sys
import os
import pytest
from dataclasses import dataclass
from playwright.sync_api import sync_playwright

# ── path fix FIRST ────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# ── import entry point ────────────────────────────────────────────────────────
from src.app.main import run_healing_agent

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ErrorReport:
    test_name: str
    selector:  str
    error:     str

# ── Session storage ───────────────────────────────────────────────────────────

_error_reports: list[ErrorReport] = []
_current_page  = None
_selector_tracker = {}  # Track which selectors returned empty/None

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def error_store() -> list[ErrorReport]:
    return _error_reports

@pytest.fixture(scope="session")
def page():
    global _current_page
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        pg      = browser.new_page()
        pg.goto("https://www.saucedemo.com/")
        _current_page = pg
        
        # Monkey-patch locator to track empty results
        original_locator = pg.locator
        def tracked_locator(selector):
            loc = original_locator(selector)
            original_all_text = loc.all_text_contents
            
            def tracked_all_text_contents():
                result = original_all_text()
                if not result:  # Empty result - track the selector
                    _selector_tracker['last_empty_selector'] = selector
                    _selector_tracker['last_empty_error'] = f"Selector '{selector}' returned no elements"
                return result
            
            loc.all_text_contents = tracked_all_text_contents
            return loc
        
        pg.locator = tracked_locator
        yield pg
        browser.close()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_selector_from_assertion(error_msg: str) -> str:
    """
    Try to extract selector from assertion error or tracked history.
    Looks for patterns like 'assert [] ==' or uses tracked selector.
    """
    # Check if tracking captured an empty selector recently
    if _selector_tracker.get('last_empty_selector'):
        return _selector_tracker['last_empty_selector']
    
    # Try to extract from error message
    match = re.search(r'locator\("([^"]+)"\)|locator\(\'([^\']+)\'\)', error_msg)
    if match:
        return match.group(1) or match.group(2)
    
    return "unknown"

def _should_trigger_agent(error_msg: str) -> bool:
    """
    Determine if agent should be triggered.
    True for: timeout, locator errors, AND assertion errors with empty results.
    """
    # Trigger for timeout errors
    if "Timeout" in error_msg:
        return True
    
    # Trigger for locator-related errors
    if "locator" in error_msg.lower():
        return True
    
    # Trigger for assertion errors comparing empty list with non-empty
    if "AssertionError" in error_msg and "assert []" in error_msg:
        return True
    
    # Trigger if we tracked an empty selector
    if _selector_tracker.get('last_empty_selector'):
        return True
    
    return False

def _extract_selector(exc_value: BaseException, item) -> str:
    manual = getattr(item, "_current_selector", None)
    if manual:
        return manual
    msg   = str(exc_value)
    return _extract_selector_from_assertion(msg)

# ── Hook ──────────────────────────────────────────────────────────────────────

@pytest.hookimpl(hookwrapper=True,trylast=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report  = outcome.get_result()

    if call.when != "call" or not report.failed:
        return

    exc       = call.excinfo
    error_msg = str(exc.value) if exc else "Unknown error"
    selector  = _extract_selector(exc.value, item) if exc else "unknown"

    # ── build and store report ────────────────────────────────────────────────
    report_obj = ErrorReport(
        test_name = item.nodeid,
        selector  = selector,
        error     = error_msg,
    )
    _error_reports.append(report_obj)

    report.sections.append((
        "Error Report",
        f"test_name : {report_obj.test_name}\n"
        f"selector  : {report_obj.selector}\n"
        f"error     : {report_obj.error}",
    ))

    # ── invoke agent for timeout, locator, AND assertion errors ──────────────
    if _current_page and _should_trigger_agent(error_msg):
        try:
            print(f"\n[agent trigger] Detected {type(exc.value).__name__}: {selector}")
            run_healing_agent(
                test_name = report_obj.test_name,
                selector  = report_obj.selector,
                error     = error_msg,
                page      = _current_page,
            )
        # except Exception as e:
            # print(f"\n[agent error] {e}")
        finally:
            # Clear tracker after agent invocation
            _selector_tracker.clear()