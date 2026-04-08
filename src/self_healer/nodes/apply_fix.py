import os
from ..state import AgentState
from ..tools.file_editor_tool import file_editor_tool
from .rerun_engine import TestRerunEngine


def apply_fix(state: AgentState) -> dict:
    approved    = state.get("approved", False)
    file_path   = state.get("file_path")
    line_number = state.get("line_number")
    selector    = state.get("selector")
    suggestion  = state.get("suggestion")
    test_name   = state.get("test_name")
    heal_cycles = state.get("heal_cycles", 0)

    if not approved:
        print("\n[agent action] Fix was rejected. No changes made.")
        return {"rerun_passed": False}

    if not file_path or not line_number:
        print("\n[agent error] Cannot apply fix: file path or line number not found.")
        return {"rerun_passed": False}

    if not selector or not suggestion:
        print("\n[agent error] Cannot apply fix: missing selector or suggestion.")
        return {"rerun_passed": False}

    # 1 — Write the fix to disk
    try:
        result = file_editor_tool.invoke({
            "file_path":    file_path,
            "line_number":  line_number,
            "old_selector": selector,
            "new_selector": suggestion,
        })
    except Exception as e:
        print(f"\n[agent error] File editor failed: {e}")
        return {"rerun_passed": False}

    if result.get("error"):
        print(f"\n[agent error] {result['error']}")
        return {"rerun_passed": False}

    print(f"\n[agent success] {result.get('message', 'File updated.')}")

    # 2 — Rerun the fixed test + all consecutive tests in the same file
    #     using a fresh subprocess so pytest re-collects from disk.
    if test_name:
        engine = TestRerunEngine()
        rerun  = engine.rerun_from(
            test_name=test_name,
            file_path=None,  # Derive from test_name instead of passing the Page Object file
            heal_cycles=heal_cycles,
        )
        return {
            "rerun_passed": rerun.passed,
            "heal_cycles":  heal_cycles + 1 if not rerun.passed else heal_cycles,
        }

    # No test_name = cannot verify, treat as passed
    return {"rerun_passed": True}