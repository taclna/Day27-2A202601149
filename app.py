"""Streamlit approval interface for the churn-risk HITL workflow."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import streamlit as st

from audit import read_audit_log
from graph import build_graph, create_initial_state


AUDIT_PATH = Path(
    os.environ.get(
        "HITL_AUDIT_PATH",
        str(Path(__file__).with_name("audit_log.json")),
    )
)

st.set_page_config(
    page_title="Churn Risk HITL",
    page_icon="👤",
    layout="wide",
)
st.title("Churn Risk Human-in-the-Loop")
st.caption(
    "LangGraph demo: đánh giá churn risk, áp dụng hard policy và yêu cầu "
    "con người phê duyệt hành động cần review."
)

if "workflow" not in st.session_state:
    st.session_state.workflow = build_graph(audit_path=AUDIT_PATH)
if "thread_config" not in st.session_state:
    st.session_state.thread_config = None
if "last_state" not in st.session_state:
    st.session_state.last_state = None


def resume_review(decision: str, reviewer_id: str, edited_action: str = "") -> None:
    """Update the pending checkpoint and resume it with the same thread ID."""

    reviewer = reviewer_id.strip()
    if not reviewer:
        raise ValueError("Reviewer ID không được để trống")

    updates = {
        "human_decision": decision,
        "reviewer_id": reviewer,
    }
    if decision == "edit":
        replacement = edited_action.strip()
        if not replacement:
            raise ValueError("Action sau khi sửa không được để trống")
        updates["edited_action"] = replacement

    st.session_state.workflow.update_state(
        st.session_state.thread_config,
        updates,
    )
    st.session_state.last_state = st.session_state.workflow.invoke(
        None,
        st.session_state.thread_config,
    )


with st.form("customer_form"):
    st.subheader("1. Dữ liệu khách hàng")
    customer_id = st.text_input("Customer ID", value="CUST001", key="customer_id")
    total_operating_income = st.number_input(
        "Total Operating Income (TOI)",
        min_value=0.0,
        value=30_000_000.0,
        step=1_000_000.0,
        key="total_operating_income",
    )
    churn_probability = st.number_input(
        "Churn probability",
        min_value=0.0,
        max_value=1.0,
        value=0.80,
        step=0.01,
        format="%.2f",
        key="churn_probability",
    )
    reviewer_id = st.text_input(
        "Reviewer ID",
        value="operator_01",
        key="reviewer_id",
    )
    evaluate_clicked = st.form_submit_button(
        "Đánh giá khách hàng",
        key="evaluate_customer",
        type="primary",
    )

if evaluate_clicked:
    try:
        initial_state = create_initial_state(
            customer_id,
            total_operating_income,
            churn_probability,
        )
        st.session_state.thread_config = {
            "configurable": {"thread_id": str(uuid4())}
        }
        st.session_state.last_state = st.session_state.workflow.invoke(
            initial_state,
            st.session_state.thread_config,
        )
    except (ValueError, OSError) as exc:
        st.error(str(exc))


if st.session_state.thread_config is not None:
    snapshot = st.session_state.workflow.get_state(st.session_state.thread_config)
    state = dict(snapshot.values)

    if state:
        st.divider()
        st.subheader("2. Đề xuất của agent")
        first, second, third = st.columns(3)
        first.metric("Customer ID", state["customer_id"])
        second.metric("Proposed action", state["proposed_action"])
        third.metric("Confidence", f"{state['confidence_score']:.2f}")
        st.info(state["reasoning"], icon="💡")

        is_pending_review = "execute_high_risk_action" in snapshot.next
        if is_pending_review:
            st.warning(
                "Graph đang tạm dừng trước execute_high_risk_action và chờ reviewer.",
                icon="⏸️",
            )
            st.subheader("3. Human review")
            approve_column, reject_column = st.columns(2)

            if approve_column.button("Approve", key="approve", type="primary"):
                try:
                    resume_review("approve", reviewer_id)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))

            if reject_column.button("Reject", key="reject"):
                try:
                    resume_review("reject", reviewer_id)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))

            edited_action = st.text_input(
                "Action thay thế",
                value=state["proposed_action"],
                key="edited_action_input",
            )
            if st.button("Edit", key="edit"):
                try:
                    resume_review("edit", reviewer_id, edited_action)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
        else:
            execution_status = state.get("execution_status", "")
            if execution_status.startswith("rejected:"):
                st.warning(f"Kết quả: {execution_status}")
            elif execution_status.startswith("executed:"):
                st.success(f"Kết quả: {execution_status}")


st.divider()
st.subheader("Audit trail")
try:
    audit_entries = read_audit_log(AUDIT_PATH)
    if audit_entries:
        st.dataframe(audit_entries, width="stretch", hide_index=True)
    else:
        st.caption("Chưa có audit entry.")
except ValueError as exc:
    st.error(str(exc))
