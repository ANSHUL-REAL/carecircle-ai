from pathlib import Path


def test_template_wires_bounded_eventbridge_scheduler() -> None:
    template = (
        Path(__file__).parents[1] / "template.yaml"
    ).read_text(encoding="utf-8")

    assert "AutomationSchedule:" in template
    assert 'ScheduleExpression: "rate(15 minutes)"' in template
    assert '"source":"carecircle.scheduler"' in template
    assert "MaximumRetryAttempts: 1" in template
    assert "MaximumEventAgeInSeconds: 900" in template
    assert "AUTO_APPROVE_OUTREACH: " in template
    assert 'MAX_CASES_PER_RUN: "25"' in template
