from app import handler as handler_module


def test_eventbridge_event_runs_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(
        handler_module,
        "run_scheduled_cycle",
        lambda: {"processed": 3},
    )

    response = handler_module.handler(
        {"source": "carecircle.scheduler"},
        None,
    )

    assert response == {
        "ok": True,
        "trigger": "eventbridge",
        "summary": {"processed": 3},
    }


def test_http_event_is_forwarded_to_mangum(monkeypatch) -> None:
    monkeypatch.setattr(
        handler_module,
        "api_handler",
        lambda event, context: {"statusCode": 200, "body": "ok"},
    )
    event = {"requestContext": {"http": {"method": "GET"}}}

    response = handler_module.handler(event, "context")

    assert response == {"statusCode": 200, "body": "ok"}
