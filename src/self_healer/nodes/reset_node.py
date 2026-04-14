from self_healer.state import AgentState


def reset_for_reheal(state: AgentState) -> dict:
    return {
        "messages":    [],
        "suggestion":  None,
        "approved":    False,
        "retry_count": 0,
    }