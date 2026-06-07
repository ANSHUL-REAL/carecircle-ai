from app.transcription import media_format_for_content_type, transcript_from_payload


def test_maps_browser_audio_content_types_to_transcribe_formats() -> None:
    assert media_format_for_content_type("audio/webm;codecs=opus") == "webm"
    assert media_format_for_content_type("audio/mp4") == "mp4"
    assert media_format_for_content_type("audio/wav") == "wav"


def test_extracts_first_transcript_from_aws_payload() -> None:
    payload = {
        "results": {
            "transcripts": [
                {"transcript": "I need A positive blood in Hyderabad."}
            ]
        }
    }

    assert transcript_from_payload(payload) == (
        "I need A positive blood in Hyderabad."
    )
