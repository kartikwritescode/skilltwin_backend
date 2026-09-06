from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)
    success: bool = True
    data: T
    message: Optional[str] = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None


class APIErrorResponse(BaseModel):
    error: ErrorDetail
