from datetime import date

import boto3
import pytest
from botocore.stub import Stubber

from app.ai import BedrockAdapter, classify_known_reply


def bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def converse_response(text: str) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
        "metrics": {"latencyMs": 1},
    }


def test_acceptance_is_classified_without_bedrock() -> None:
    result = classify_known_reply("Yes, I can donate tomorrow")

    assert result.status == "accepted"
    assert result.needs_ai is False
    assert result.confidence == 1.0


def test_decline_unavailable_and_opt_out_are_classified_locally() -> None:
    assert classify_known_reply("Sorry, I cannot donate").status == "declined"
    assert classify_known_reply("I am out of station").status == "unavailable"
    assert classify_known_reply("Stop messaging me").status == "opt_out"


def test_unclear_reply_requires_bedrock() -> None:
    result = classify_known_reply("Maybe, let me see")

    assert result.status == "unclear"
    assert result.needs_ai is True


@pytest.mark.parametrize(
    "text",
    [
        "No problem, I can donate",
        "I am not available",
        "don't stop messaging me",
        "not sick",
    ],
)
def test_mixed_or_negated_phrases_fall_back_to_bedrock(text: str) -> None:
    result = classify_known_reply(text)

    assert result.status == "unclear"
    assert result.needs_ai is True


def test_bedrock_reply_classifier_parses_json_response() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")

    with Stubber(client) as stubber:
        stubber.add_response(
            "converse",
            converse_response(
                '{"status":"accepted","confidence":0.82,'
                '"available_from":"2026-06-07T10:00:00Z",'
                '"location":"Dehradun","notes":"Can come morning"}'
            ),
        )
        result = adapter.classify_reply("Can come morning")

    assert result.status == "accepted"
    assert result.confidence == 0.82
    assert result.location == "Dehradun"


def test_bedrock_request_extraction_validates_blood_request() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")

    with Stubber(client) as stubber:
        stubber.add_response(
            "converse",
            converse_response(
                '{"request":{"patient_name":"Asha",'
                '"blood_group":"o-","units":2,'
                '"hospital":"Doon Hospital","city":"Dehradun",'
                '"deadline":"2026-06-09","urgency":"critical"},'
                '"missing_fields":[]}'
            ),
        )
        result = adapter.extract_request("Need O negative for Asha")

    assert result.request is not None
    assert result.request.blood_group == "O-"
    assert result.request.deadline == date(2026, 6, 9)
    assert result.missing_fields == []


def test_bedrock_invalid_json_raises_clear_error() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")

    with Stubber(client) as stubber:
        stubber.add_response("converse", converse_response("not json"))
        with pytest.raises(ValueError, match="valid JSON"):
            adapter.classify_reply("unclear")


def test_bedrock_reply_classifier_requires_requested_keys() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")

    with Stubber(client) as stubber:
        stubber.add_response(
            "converse",
            converse_response('{"status":"accepted","confidence":0.8}'),
        )
        with pytest.raises(ValueError, match="missing required keys"):
            adapter.classify_reply("yes")


def test_bedrock_request_extraction_requires_missing_fields_key() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")

    with Stubber(client) as stubber:
        stubber.add_response("converse", converse_response('{"request":null}'))
        with pytest.raises(ValueError, match="missing required keys"):
            adapter.extract_request("unknown")


def test_bedrock_reads_later_text_blocks() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")
    response = converse_response(
        '{"status":"accepted","confidence":0.8,'
        '"available_from":null,"location":null,"notes":""}'
    )
    response["output"]["message"]["content"].insert(0, {"text": ""})

    with Stubber(client) as stubber:
        stubber.add_response("converse", response)
        result = adapter.classify_reply("yes")

    assert result.status == "accepted"


def test_bedrock_missing_text_blocks_raises_clear_error() -> None:
    client = bedrock_client()
    adapter = BedrockAdapter(client=client, model_id="test-model")
    response = converse_response("{}")
    response["output"]["message"]["content"] = []

    with Stubber(client) as stubber:
        stubber.add_response("converse", response)
        with pytest.raises(ValueError, match="No text content"):
            adapter.classify_reply("yes")
