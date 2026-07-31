"""
src/eval/tracing.py — LangSmith LLMOps tracing and telemetry setup.

Configures LangSmith tracing for LangChain / LangGraph calls without breaking execution
if API keys are missing or invalid.
"""

from __future__ import annotations

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def init_langsmith_tracing(project_name: str = "recovery-team-eval") -> bool:
    """Initialize LangSmith tracing environment variables.

    Returns True if tracing is active, False otherwise.
    """
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("[tracing] Warning: LANGCHAIN_API_KEY / LANGSMITH_API_KEY not set. Tracing disabled.")
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project_name
    print(f"[tracing] LangSmith tracing initialized for project '{project_name}'.")
    return True


if __name__ == "__main__":
    active = init_langsmith_tracing()
    print(f"Tracing Status: {'Active' if active else 'Disabled'}")
