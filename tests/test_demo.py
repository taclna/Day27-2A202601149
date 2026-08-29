from demo import run_demo


def test_cli_demo_completes_low_risk_workflow(tmp_path):
    result = run_demo(audit_path=tmp_path / "audit.json")

    assert result["customer_id"] == "DEMO-CUST-001"
    assert result["execution_status"] == "executed:send_email"
