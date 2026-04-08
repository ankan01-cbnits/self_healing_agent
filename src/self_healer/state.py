from typing import List, TypedDict, Optional, Annotated
from langchain_core.messages import BaseMessage
import operator

class AgentState(TypedDict):
    test_name:   str
    selector:    str
    error:       str
    dom_context: str
    suggestion:  Optional[str]
    confidence:  float
    reason:      Optional[str]
    step_passed: bool
    messages:    Annotated[list[BaseMessage], operator.add]
      
    #tools
    approved:    bool
    file_path:   Optional[str]
    line_number: Optional[int]

    #xpath 
    is_xpath:       bool                 # detected by dom_extractor
    intent: str
    wait_strategy: Optional[str]
    failure_mode: Optional[str]
    retry_count: int
    rerun_passed: bool
    heal_cycles:  int 