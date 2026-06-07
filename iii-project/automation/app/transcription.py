import json
import os
import subprocess
import time
from tempfile import NamedTemporaryFile
from urllib.request import urlopen
from uuid import uuid4

import boto3
from vosk import KaldiRecognizer, Model


_vosk_model = None


def media_format_for_content_type(content_type: str | None) -> str:
    value = (content_type or "").lower()
    if "webm" in value:
        return "webm"
    if "mp4" in value or "m4a" in value:
        return "mp4"
    if "wav" in value:
        return "wav"
    if "mpeg" in value or "mp3" in value:
        return "mp3"
    raise ValueError("Unsupported microphone audio format")


def transcript_from_payload(payload: dict) -> str:
    transcripts = payload.get("results", {}).get("transcripts", [])
    if not transcripts:
        return ""
    return str(transcripts[0].get("transcript") or "").strip()


def transcribe_audio_with_aws(
    audio: bytes,
    content_type: str | None,
    bucket: str,
    *,
    language_code: str = "en-IN",
) -> str:
    media_format = media_format_for_content_type(content_type)
    job_name = f"carecircle-voice-{uuid4()}"
    object_key = f"voice-input/{job_name}.{media_format}"
    s3 = boto3.client("s3")
    transcribe = boto3.client("transcribe")

    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=audio,
        ContentType=content_type or "application/octet-stream",
    )
    try:
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            LanguageCode=language_code,
            MediaFormat=media_format,
            Media={"MediaFileUri": f"s3://{bucket}/{object_key}"},
        )
        for _ in range(45):
            result = transcribe.get_transcription_job(
                TranscriptionJobName=job_name
            )["TranscriptionJob"]
            status = result["TranscriptionJobStatus"]
            if status == "COMPLETED":
                uri = result["Transcript"]["TranscriptFileUri"]
                with urlopen(uri, timeout=15) as response:
                    return transcript_from_payload(
                        json.loads(response.read().decode("utf-8"))
                    )
            if status == "FAILED":
                raise RuntimeError(
                    result.get("FailureReason", "AWS transcription failed")
                )
            time.sleep(1)
        raise TimeoutError("AWS transcription timed out")
    finally:
        try:
            transcribe.delete_transcription_job(
                TranscriptionJobName=job_name
            )
        except Exception:
            pass
        try:
            s3.delete_object(Bucket=bucket, Key=object_key)
        except Exception:
            pass


def transcribe_audio_locally(
    audio: bytes,
    content_type: str | None,
    model_path: str,
) -> str:
    global _vosk_model
    media_format = media_format_for_content_type(content_type)
    with NamedTemporaryFile(suffix=f".{media_format}") as source:
        source.write(audio)
        source.flush()
        conversion = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                source.name,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "s16le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        )
    if _vosk_model is None:
        _vosk_model = Model(model_path)
    recognizer = KaldiRecognizer(_vosk_model, 16000)
    recognizer.AcceptWaveform(conversion.stdout)
    return str(json.loads(recognizer.FinalResult()).get("text") or "").strip()


def transcribe_audio(
    audio: bytes,
    content_type: str | None,
    bucket: str,
    *,
    language_code: str = "en-IN",
) -> str:
    provider = os.getenv("TRANSCRIPTION_PROVIDER", "vosk").casefold()
    if provider == "aws":
        return transcribe_audio_with_aws(
            audio,
            content_type,
            bucket,
            language_code=language_code,
        )
    return transcribe_audio_locally(
        audio,
        content_type,
        os.getenv("VOSK_MODEL_PATH", "/opt/vosk-model"),
    )
