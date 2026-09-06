from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    timezone: str = "UTC"
    preferences: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class UserProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    timezone: Optional[str] = Field(None, max_length=50)
    preferences: Optional[Dict[str, Any]] = None
