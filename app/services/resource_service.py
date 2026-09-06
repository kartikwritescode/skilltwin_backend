import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from app.domain.resources.models import Resource, ResourceChunk, ResourceType, ProcessingStatus
from app.domain.concepts.models import Concept
from app.repositories.resource_repository import ResourceRepository, resource_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.services.document_processor import DocumentProcessor, document_processor
from app.services.chunker import Chunker, chunker
from app.services.embedding_service import EmbeddingService, embedding_service
from app.services.concept_extractor import ConceptExtractor, concept_extractor
from app.schemas.resources import ResourceResponse, RAGChunkResult, RAGSearchResponse
from app.core.exceptions import EntityNotFoundError
from app.core.logging import logger


class ResourceService:
    """
    Resource Intelligence Pipeline:
    Manages asynchronous ingestion, text extraction, cleaning, chunking,
    concept extraction, vector embeddings, journey linking, and RAG retrieval.
    """

    def __init__(
        self,
        resource_repo: ResourceRepository = resource_repository,
        concept_repo: ConceptRepository = concept_repository,
        journey_repo: JourneyRepository = journey_repository,
        goal_repo: GoalRepository = goal_repository,
        processor: DocumentProcessor = document_processor,
        text_chunker: Chunker = chunker,
        embedder: EmbeddingService = embedding_service,
        extractor: ConceptExtractor = concept_extractor,
    ):
        self.resource_repo = resource_repo
        self.concept_repo = concept_repo
        self.journey_repo = journey_repo
        self.goal_repo = goal_repo
        self.processor = processor
        self.chunker = text_chunker
        self.embedder = embedder
        self.extractor = extractor

    async def upload_resource(
        self,
        user_id: str,
        filename: str,
        file_bytes: bytes,
        title: Optional[str] = None,
        is_public: bool = False,
    ) -> ResourceResponse:
        resource_id = f"res_{uuid.uuid4().hex[:10]}"
        res_title = title or filename.rsplit(".", 1)[0].replace("_", " ").title()

        res_type = ResourceType.TEXT
        if filename.lower().endswith(".pdf"):
            res_type = ResourceType.PDF

        # Storage path (Simulated Supabase Storage bucket / path)
        storage_path = f"supabase_storage://resources/{user_id}/{resource_id}_{filename}"

        resource = Resource(
            id=resource_id,
            user_id=user_id,
            title=res_title,
            resource_type=res_type,
            storage_path=storage_path,
            processing_status=ProcessingStatus.PROCESSING,
            is_public=is_public,
            metadata={"original_filename": filename, "file_size_bytes": len(file_bytes)},
        )
        await self.resource_repo.save(resource)
        logger.info(f"Registered upload {resource_id} ('{res_title}') - triggering background processing")

        # Asynchronous non-blocking background processing
        asyncio.create_task(self._process_pipeline(resource.id, file_bytes, filename, user_id))

        return self._to_response(resource)

    async def _process_pipeline(self, resource_id: str, file_bytes: bytes, filename: str, user_id: str):
        resource = await self.resource_repo.get_by_id(resource_id)
        if not resource:
            return

        try:
            # 1. Text Extraction & Cleaning
            cleaned_text = self.processor.extract_text(file_bytes, filename)
            if not cleaned_text:
                resource.processing_status = ProcessingStatus.COMPLETED
                resource.updated_at = datetime.now(timezone.utc)
                await self.resource_repo.save(resource)
                return

            # 2. Semantic Chunking
            raw_chunks = self.chunker.chunk_text(cleaned_text, resource_id)

            # 3. Concept Extraction
            extracted_plan = await self.extractor.extract_concepts(cleaned_text)
            extracted_concept_names = [c.name for c in extracted_plan.concepts]
            resource.extracted_concepts = extracted_concept_names

            # 4. Connect Extracted Concepts to Concepts Repository and Journey Nodes
            primary_concept_id = None
            if extracted_plan.concepts:
                first_c = extracted_plan.concepts[0]
                c_id = f"concept_{first_c.name.lower().replace(' ', '_')}"
                primary_concept_id = c_id
                existing_c = await self.concept_repo.get_by_id(c_id)
                if not existing_c:
                    await self.concept_repo.save(
                        Concept(
                            id=c_id,
                            name=first_c.name,
                            description=first_c.description,
                            domain=extracted_plan.primary_domain or "Software Engineering",
                            difficulty_level=first_c.difficulty_level,
                            prerequisites=first_c.prerequisites,
                        )
                    )

                # Connect to user journey where appropriate
                active_goal = await self.goal_repo.get_active_goal_for_user(user_id)
                if active_goal:
                    journey = await self.journey_repo.get_by_goal_id(active_goal.id)
                    if journey and journey.nodes:
                        for n in journey.nodes:
                            if any(c_name.lower() in n.title.lower() for c_name in extracted_concept_names):
                                if "linked_resources" not in n.metadata:
                                    n.metadata["linked_resources"] = []
                                if resource_id not in n.metadata["linked_resources"]:
                                    n.metadata["linked_resources"].append(resource_id)
                        await self.journey_repo.save(journey)

            # 5. Embeddings generation
            chunk_contents = [c["content"] for c in raw_chunks]
            embeddings = await self.embedder.embed_texts(chunk_contents)

            # 6. Save chunks with embeddings (pgvector representation)
            for idx, raw_c in enumerate(raw_chunks):
                emb = embeddings[idx] if idx < len(embeddings) else []
                chunk_id = f"chk_{uuid.uuid4().hex[:10]}"
                chunk_obj = ResourceChunk(
                    id=chunk_id,
                    resource_id=resource_id,
                    content=raw_c["content"],
                    chunk_index=raw_c["chunk_index"],
                    concept_id=primary_concept_id,
                    embedding=emb,
                    metadata=raw_c.get("metadata", {}),
                )
                await self.resource_repo.save_chunk(chunk_obj)
                resource.chunks.append(chunk_obj)

            resource.processing_status = ProcessingStatus.COMPLETED
            resource.updated_at = datetime.now(timezone.utc)
            await self.resource_repo.save(resource)
            logger.info(f"Resource pipeline completed for {resource_id} ({len(resource.chunks)} chunks)")

        except Exception as e:
            logger.exception(f"Pipeline failure for resource {resource_id}: {e}")
            resource.processing_status = ProcessingStatus.FAILED
            resource.error_message = str(e)
            resource.updated_at = datetime.now(timezone.utc)
            await self.resource_repo.save(resource)

    async def list_resources(self, user_id: str) -> List[ResourceResponse]:
        resources = await self.resource_repo.list_for_user(user_id, include_public=True)
        return [self._to_response(r) for r in resources]

    async def get_resource(self, user_id: str, resource_id: str) -> ResourceResponse:
        resource = await self.resource_repo.get_by_id(resource_id)
        if not resource or (resource.user_id != user_id and not resource.is_public):
            raise EntityNotFoundError("Resource", resource_id)
        return self._to_response(resource)

    async def delete_resource(self, user_id: str, resource_id: str) -> bool:
        resource = await self.resource_repo.get_by_id(resource_id)
        if not resource:
            raise EntityNotFoundError("Resource", resource_id)
        if resource.user_id != user_id:
            raise EntityNotFoundError("Resource", resource_id)

        return await self.resource_repo.delete(resource_id)

    async def retrieve_relevant_chunks(
        self,
        user_id: str,
        concept_id: Optional[str] = None,
        query: str = "",
        top_k: int = 4,
    ) -> List[RAGChunkResult]:
        logger.info(f"RAG Retrieval for user '{user_id}', concept='{concept_id}', query='{query}'")

        query_embedding = await self.embedder.embed_query(query) if query else []

        scored_chunks = await self.resource_repo.similarity_search(
            query_embedding=query_embedding,
            user_id=user_id,
            concept_id=concept_id,
            top_k=top_k,
        )

        results = []
        for chunk, score in scored_chunks:
            parent_resource = await self.resource_repo.get_by_id(chunk.resource_id)
            title = parent_resource.title if parent_resource else "Resource"
            is_pub = parent_resource.is_public if parent_resource else False
            results.append(
                RAGChunkResult(
                    chunk_id=chunk.id,
                    resource_id=chunk.resource_id,
                    resource_title=title,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    concept_id=chunk.concept_id,
                    similarity_score=round(score, 4),
                    is_public=is_pub,
                )
            )

        return results

    def _to_response(self, r: Resource) -> ResourceResponse:
        return ResourceResponse(
            id=r.id,
            user_id=r.user_id,
            title=r.title,
            resource_type=r.resource_type,
            storage_path=r.storage_path,
            processing_status=r.processing_status,
            is_public=r.is_public,
            error_message=r.error_message,
            extracted_concepts=r.extracted_concepts,
            chunk_count=len(r.chunks),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )


resource_service = ResourceService()

