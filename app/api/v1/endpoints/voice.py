from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, status
from app.core.security import CurrentUser, get_current_user
from app.services.stt_service import SpeechToTextService, stt_service
from app.services.topic_interaction_service import TopicInteractionService, topic_interaction_service
from app.schemas.teach import AudioTranscriptionResponse
from app.schemas.dynamic_learning import ContextualAskResponse

router = APIRouter(prefix="/voice", tags=["Voice Interaction Pipeline"])


@router.post(
    "/transcribe",
    response_model=AudioTranscriptionResponse,
    summary="Transcribe Spoken Voice (Speech-to-Text)",
)
async def transcribe_voice(
    file: UploadFile = File(..., description="Recorded audio (WAV, MP3, M4A, WebM, OGG)"),
    topic_hint: Optional[str] = Form(None, description="Optional topic context hint"),
    current_user: CurrentUser = Depends(get_current_user),
    stt: SpeechToTextService = Depends(lambda: stt_service),
):
    """
    Transcribes learner microphone speech to text using multimodal AI.
    Handles network timeouts and audio normalization.
    """
    audio_bytes = await file.read()
    result = await stt.transcribe_audio(
        audio_bytes=audio_bytes,
        filename=file.filename or "recording.wav",
        mime_type=file.content_type,
        concept_hint=topic_hint,
    )
    return AudioTranscriptionResponse(
        transcript=result.transcript,
        duration_seconds=result.duration_seconds,
        word_count=result.word_count,
        confidence=result.confidence,
        detected_language=result.detected_language,
    )


@router.post(
    "/ask",
    response_model=ContextualAskResponse,
    summary="Voice-Driven Contextual Question Pipeline (STT -> RAG -> LLM -> TTS)",
)
async def voice_ask(
    file: UploadFile = File(..., description="Audio recording of question"),
    topic_id: Optional[str] = Form(None, description="Current topic ID context"),
    current_user: CurrentUser = Depends(get_current_user),
    stt: SpeechToTextService = Depends(lambda: stt_service),
    topic_svc: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """
    End-to-end voice question pipeline:
    1. Transcribes audio input via STT
    2. Scopes to current topic
    3. Retrieves grounded RAG chunks
    4. Generates concise Socratic answer
    5. Returns text and TTS audio prompt
    """
    audio_bytes = await file.read()
    transcription = await stt.transcribe_audio(
        audio_bytes=audio_bytes,
        filename=file.filename or "question.wav",
        mime_type=file.content_type,
        concept_hint=topic_id,
    )

    query = transcription.transcript.strip()
    if not query:
        return ContextualAskResponse(
            answer="I couldn't clearly detect your question. Please try speaking again.",
            sources=[],
            suggested_followups=[],
            audio_tts_text="I couldn't clearly detect your question. Please try speaking again.",
        )

    return await topic_svc.ask_topic_question(
        user_id=current_user.user_id,
        topic_id=topic_id or "",
        query=query,
    )
