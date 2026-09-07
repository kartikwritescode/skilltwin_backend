"""
Centralized Versioned Prompt Registry (v1).
"""
from app.ai.prompts.v1 import (
    learning_path,
    topic_explanation,
    revision,
    question_generation,
    assessment,
    twin_update,
    recommendation,
)

__all__ = [
    "learning_path",
    "topic_explanation",
    "revision",
    "question_generation",
    "assessment",
    "twin_update",
    "recommendation",
]
