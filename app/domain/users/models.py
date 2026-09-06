from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional


@dataclass
class UserProfile:
    id: str
    email: str
    full_name: str
    timezone: str = "UTC"
    preferences: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
