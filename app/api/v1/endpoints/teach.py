from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form
from app.core.security import CurrentUser, get_current_user
from app.schemas.teach import (
    AudioTranscriptionResponse,
    TeachEvaluateRequest,
    TeachEvaluationResponse,
)
from app.services.stt_service import SpeechToTextService, stt_service
from app.services.teach_service import TeachService, teach_service

router = APIRouter(prefix="/teach", tags=["Teach Mode"])


@router.post(
    "/transcribe",
    response_model=AudioTranscriptionResponse,
    summary="Transcribe Learner Voice Explanation (Speech-to-Text)",
)
async def transcribe_audio_explanation(
    file: UploadFile = File(..., description="Recorded audio explanation (WAV, MP3, M4A, WebM, OGG)"),
    concept_id: Optional[str] = Form(None, description="Optional concept context hint for acoustic modeling"),
    current_user: CurrentUser = Depends(get_current_user),
    stt: SpeechToTextService = Depends(lambda: stt_service),
):
    """
    Transcribes learner speech into text for Feynman teach-back analysis.
    Validates audio format, duration, and extracts operational transcription.
    """
    content = await file.read()
    result = await stt.transcribe_audio(
        audio_bytes=content,
        filename=file.filename or "audio_recording.wav",
        mime_type=file.content_type,
        concept_hint=concept_id,
    )

    return AudioTranscriptionResponse(
        transcript=result.transcript,
        duration_seconds=result.duration_seconds,
        word_count=result.word_count,
        confidence=result.confidence,
        detected_language=result.detected_language,
    )


@router.post(
    "/evaluate",
    response_model=TeachEvaluationResponse,
    summary="Evaluate Teach-Back Explanation & Update Learner Model",
)
async def evaluate_teach_explanation(
    request: TeachEvaluateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: TeachService = Depends(lambda: teach_service),
):
    """
    Evaluates a learner's teach-back explanation using the Feynman technique.

    Pipeline:
    Transcript + Learner Context -> LLM Evaluator -> EvaluationService -> LearnerService -> State & Journey Recalibration.

    Enforces mandatory separation: The LLM evaluator does not directly write to the database.
    Outputs are validated by EvaluationService and deterministically persisted by LearnerService.
    """
    return await service.evaluate_teach_session(
        user_id=current_user.user_id,
        request=request,
    )
