import os
from dataclasses import dataclass
from typing import Optional, Protocol
from app.core.exceptions import ValidationError
from app.core.logging import logger


@dataclass
class AudioTranscriptionResult:
    transcript: str
    duration_seconds: float
    word_count: int
    confidence: float
    detected_language: str = "en"


class SpeechToTextProvider(Protocol):
    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        mime_type: str = "audio/wav",
        concept_hint: Optional[str] = None,
    ) -> AudioTranscriptionResult:
        ...


class MockSpeechToTextProvider:
    """
    Mock speech-to-text provider for local offline operation and deterministic automated tests.
    Transcribes audio bytes into high-fidelity technical explanations.
    """

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        mime_type: str = "audio/wav",
        concept_hint: Optional[str] = None,
    ) -> AudioTranscriptionResult:
        logger.info(f"Mock STT transcribing {len(audio_bytes)} bytes from '{filename}' ({mime_type})")

        # Check if the audio file contains encoded utf-8 test text
        decoded_text = ""
        try:
            raw_str = audio_bytes.decode("utf-8", errors="ignore").strip()
            # If the payload was text passed in test
            if len(raw_str) > 10 and any(c.isalpha() for c in raw_str):
                decoded_text = raw_str
        except Exception:
            pass

        if decoded_text:
            transcript = decoded_text
        elif concept_hint and "stream" in concept_hint.lower():
            transcript = (
                "Dart Streams provide an asynchronous sequence of events. A StreamController "
                "manages both the sink for adding data and the stream that subscribers listen to. "
                "Broadcast streams allow multiple listeners, whereas single-subscription streams "
                "buffer events until a listener attaches."
            )
        elif concept_hint and "recursion" in concept_hint.lower():
            transcript = (
                "Recursion works by decomposing a computational problem into identical smaller instances. "
                "Each recursive invocation allocates an activation record on the call stack. "
                "The invariant base case is mandatory to halt the recurrence relation and unwind the stack frames."
            )
        else:
            transcript = (
                "Recursion solves algorithmic tasks by dividing input state towards a strictly defined base case. "
                "When the base condition evaluates to true, stack frames pop and return values backwards."
            )

        duration = max(8.5, round(len(audio_bytes) / 12000.0, 1))
        words = len(transcript.split())

        return AudioTranscriptionResult(
            transcript=transcript,
            duration_seconds=duration,
            word_count=words,
            confidence=0.96,
            detected_language="en",
        )


class SpeechToTextService:
    """
    High-level speech-to-text pipeline orchestrator.
    Validates audio format, size, and executes transcription.
    """

    SUPPORTED_MIME_TYPES = {
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/webm",
        "audio/ogg",
        "audio/aac",
        "application/octet-stream",
    }
    MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB

    def __init__(self, provider: Optional[SpeechToTextProvider] = None):
        self.provider = provider or MockSpeechToTextProvider()

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        mime_type: Optional[str] = None,
        concept_hint: Optional[str] = None,
    ) -> AudioTranscriptionResult:
        if not audio_bytes or len(audio_bytes) == 0:
            raise ValidationError("Audio payload cannot be empty.")

        if len(audio_bytes) > self.MAX_AUDIO_BYTES:
            raise ValidationError(f"Audio file exceeds maximum allowed size of {self.MAX_AUDIO_BYTES // (1024*1024)}MB.")

        cleaned_mime = (mime_type or "audio/wav").lower().split(";")[0].strip()
        if cleaned_mime not in self.SUPPORTED_MIME_TYPES:
            # Check extension fallback
            _, ext = os.path.splitext(filename)
            ext_clean = ext.lower().lstrip(".")
            if ext_clean not in {"wav", "mp3", "m4a", "webm", "ogg", "aac"}:
                raise ValidationError(
                    f"Unsupported audio format '{mime_type}'. Supported formats: WAV, MP3, M4A, WebM, OGG, AAC."
                )

        return await self.provider.transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            mime_type=cleaned_mime,
            concept_hint=concept_hint,
        )


stt_service = SpeechToTextService()
