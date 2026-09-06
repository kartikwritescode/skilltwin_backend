from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.domain.resources.models import ResourceType, ProcessingStatus

class ResourceChunkSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    resource_id: str
    content: str
    chunk_index: int
    concept_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    title: str
    resource_type: ResourceType
    storage_path: Optional[str] = None
    processing_status: ProcessingStatus
    is_public: bool = False
    error_message: Optional[str] = None
    extracted_concepts: List[str] = Field(default_factory=list)
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

class RAGChunkResult(BaseModel):
    chunk_id: str
    resource_id: str
    resource_title: str
    content: str
    chunk_index: int
    concept_id: Optional[str] = None
    similarity_score: float
    is_public: bool = False

class RAGSearchRequest(BaseModel):
    query: str
    concept_id: Optional[str] = None
    top_k: int = 4

class RAGSearchResponse(BaseModel):
    query: str
    concept_id: Optional[str] = None
    total_found: int
    results: List[RAGChunkResult]
