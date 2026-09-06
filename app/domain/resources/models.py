from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List


class ResourceType(str, Enum):
    PDF = "pdf"
    TEXT = "text"
    LINK = "link"
    NOTE = "note"


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ResourceChunk:
    id: str
    resource_id: str
    content: str
    chunk_index: int
    concept_id: Optional[str] = None
    embedding: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Resource:
    id: str
    user_id: str
    title: str
    resource_type: ResourceType
    storage_path: Optional[str] = None
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    is_public: bool = False
    error_message: Optional[str] = None
    extracted_concepts: List[str] = field(default_factory=list)
    chunks: List[ResourceChunk] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

