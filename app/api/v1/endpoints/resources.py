from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, status
from app.schemas.resources import ResourceResponse, RAGSearchRequest, RAGSearchResponse
from app.services.resource_service import ResourceService, resource_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/resources", tags=["Resources"])

@router.post("/upload", response_model=ResourceResponse, status_code=status.HTTP_202_ACCEPTED, summary="Upload Resource (Async Pipeline)")
async def upload_resource(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    is_public: bool = Form(False),
    current_user: CurrentUser = Depends(get_current_user),
    service: ResourceService = Depends(lambda: resource_service),
):
    file_bytes = await file.read()
    return await service.upload_resource(
        user_id=current_user.user_id,
        filename=file.filename or "document.txt",
        file_bytes=file_bytes,
        title=title,
        is_public=is_public,
    )

@router.get("", response_model=List[ResourceResponse], status_code=status.HTTP_200_OK, summary="List Resources")
async def list_resources(
    current_user: CurrentUser = Depends(get_current_user),
    service: ResourceService = Depends(lambda: resource_service),
):
    return await service.list_resources(user_id=current_user.user_id)

@router.get("/{resource_id}", response_model=ResourceResponse, status_code=status.HTTP_200_OK, summary="Get Resource Details")
async def get_resource(
    resource_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: ResourceService = Depends(lambda: resource_service),
):
    return await service.get_resource(user_id=current_user.user_id, resource_id=resource_id)

@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Resource")
async def delete_resource(
    resource_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: ResourceService = Depends(lambda: resource_service),
):
    await service.delete_resource(user_id=current_user.user_id, resource_id=resource_id)

@router.post("/search", response_model=RAGSearchResponse, status_code=status.HTTP_200_OK, summary="RAG Vector Search")
async def search_resources(
    request: RAGSearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ResourceService = Depends(lambda: resource_service),
):
    chunks = await service.retrieve_relevant_chunks(
        user_id=current_user.user_id,
        concept_id=request.concept_id,
        query=request.query,
        top_k=request.top_k,
    )
    return RAGSearchResponse(
        query=request.query,
        concept_id=request.concept_id,
        total_found=len(chunks),
        results=chunks,
    )
