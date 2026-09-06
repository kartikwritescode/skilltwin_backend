from typing import Dict
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str = "ok"
    version: str = "1.0.0"
    service: str = "SkillTwin Backend"
    environment: str
    dependencies: Dict[str, str]
