from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List

T = TypeVar("T")
ID = TypeVar("ID")


class BaseRepository(ABC, Generic[T, ID]):
    """Abstract base repository interface defining essential CRUD operations."""

    @abstractmethod
    async def get_by_id(self, entity_id: ID) -> Optional[T]:
        pass

    @abstractmethod
    async def list_all(self) -> List[T]:
        pass

    @abstractmethod
    async def save(self, entity: T) -> T:
        pass

    @abstractmethod
    async def delete(self, entity_id: ID) -> bool:
        pass
