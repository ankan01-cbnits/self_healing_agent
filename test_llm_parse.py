import sys
import os
import traceback

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from self_healer.nodes.llm_reason import _parse_llm_output

outputs = [
    """Here is my suggestion:
```json
{
  "suggestion": "#login-button",
  "reason": "The original selector was incorrect...",
  "confidence": "95%",
  "intent": "login action"
}
```
Hope this helps!""",
    """
{
  "suggestion": "//button['click me']",
  "reason": "Some reason.",
  "confidence": 85.5,
  "intent": "Unknown"
}
    """
]

with open("test_llm_output.txt", "w") as f:
    for out in outputs:
        try:
            res = _parse_llm_output(out)
            f.write(str(res) + "\n")
        except Exception as e:
            f.write(traceback.format_exc() + "\n")
