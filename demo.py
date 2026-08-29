"""Command-line demonstration of the low-risk LangGraph path."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from graph import build_graph, create_initial_state


def run_demo(audit_path: str | Path = Path("audit_log.json")) -> dict[str, object]:
    """Run a deterministic customer through the auto-execute path."""

    workflow = build_graph(audit_path=audit_path)
    config = {"configurable": {"thread_id": str(uuid4())}}
    state = create_initial_state("DEMO-CUST-001", 10_000_000, 0.20)
    return workflow.invoke(state, config)


def main() -> None:
    """Print the demo result in a reviewer-friendly format."""

    result = run_demo()
    print(f"Customer ID: {result['customer_id']}")
    print(f"Proposed action: {result['proposed_action']}")
    print(f"Confidence: {result['confidence_score']:.2f}")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Execution status: {result['execution_status']}")


if __name__ == "__main__":
    main()
