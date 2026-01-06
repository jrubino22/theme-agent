from pathlib import Path
from typing import Dict, Any

def create_plan(task: Dict[str, Any], recon: Dict[str, Any], theme_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder planner.
    Later this will be driven by an LLM.
    """
    return {
        "intent": "UNKNOWN",
        "assumptions": [],
        "file_operations": [],
        "reuse_candidates": [],
        "new_files": [],
        "risks": [],
    }