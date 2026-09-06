from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse
from app.core.logging import logger


class SkillTwinException(Exception):
    """Base domain exception for SkillTwin."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class EntityNotFoundError(SkillTwinException):
    def __init__(self, entity_name: str, entity_id: Any):
        super().__init__(
            message=f"{entity_name} with ID '{entity_id}' was not found.",
            code="ENTITY_NOT_FOUND",
            details={"entity_name": entity_name, "entity_id": str(entity_id)}
        )


class EntityConflictError(SkillTwinException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="ENTITY_CONFLICT", details=details)


class ValidationError(SkillTwinException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="VALIDATION_ERROR", details=details)


class UnauthorizedError(SkillTwinException):
    def __init__(self, message: str = "Authentication credentials required or invalid."):
        super().__init__(message=message, code="UNAUTHORIZED")


class AIProviderError(SkillTwinException):
    def __init__(self, message: str, provider: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"AI Provider ({provider}) error: {message}",
            code="AI_PROVIDER_ERROR",
            details={"provider": provider, **(details or {})}
        )


async def domain_exception_handler(request: Request, exc: SkillTwinException) -> JSONResponse:
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    if isinstance(exc, EntityNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, EntityConflictError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, ValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, UnauthorizedError):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, AIProviderError):
        status_code = status.HTTP_502_BAD_GATEWAY

    logger.warning(
        f"Domain exception on {request.method} {request.url.path}: {exc.code} - {exc.message}"
    )

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details
            }
        }
    )
