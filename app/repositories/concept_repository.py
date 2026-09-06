from typing import Optional, List, Dict, Any, Set
from app.repositories.base import BaseRepository
from app.domain.concepts.models import Concept, ConceptEdge, RelationshipType


class ConceptRepository(BaseRepository[Concept, str]):
    """Manages concepts, graph edges, prerequisite chains, and downstream impact."""

    def __init__(self):
        self._concepts: Dict[str, Concept] = {}
        self._edges: List[ConceptEdge] = []
        self._seed_default_concepts()

    def _seed_default_concepts(self):
        sample_concepts = [
            Concept(
                id="concept_dart_basics",
                name="Dart Fundamentals & Type System",
                description="Core syntax, sound null safety, collections, classes, and language ergonomics.",
                domain="Flutter",
                difficulty_level="beginner",
                prerequisites=[],
            ),
            Concept(
                id="concept_dart_async_and_streams",
                name="Dart Async & Streams",
                description="Understand StreamControllers, Futures, microtask queues, and asynchronous event handling.",
                domain="Flutter",
                difficulty_level="intermediate",
                prerequisites=["concept_dart_basics"],
            ),
            Concept(
                id="concept_state_management",
                name="State Management Architecture",
                description="Predictable unidirectional data flow, caching, and reactivity using Riverpod / Bloc.",
                domain="Flutter",
                difficulty_level="advanced",
                prerequisites=["concept_dart_async_and_streams"],
            ),
            Concept(
                id="concept_functions_and_scope",
                name="Functions & Memory Scopes",
                description="Call stacks, lexical closures, parameter passing, and frame allocation.",
                domain="Computer Science",
                difficulty_level="beginner",
                prerequisites=[],
            ),
            Concept(
                id="concept_stack_memory",
                name="Call Stack & Heap Invariants",
                description="Activation records, pointer references, stack overflow thresholds, and memory layout.",
                domain="Computer Science",
                difficulty_level="intermediate",
                prerequisites=["concept_functions_and_scope"],
            ),
            Concept(
                id="concept_recursion",
                name="Recursion & Recurrence",
                description="Solving problems by breaking them down into smaller sub-problems with invariant base cases.",
                domain="Computer Science",
                difficulty_level="intermediate",
                prerequisites=["concept_functions_and_scope", "concept_stack_memory"],
            ),
            Concept(
                id="concept_tree_traversal",
                name="Tree Traversal Algorithms",
                description="Recursive and iterative DFS/BFS, preorder, inorder, and level-order search patterns.",
                domain="Computer Science",
                difficulty_level="advanced",
                prerequisites=["concept_recursion"],
            ),
        ]
        for c in sample_concepts:
            self._concepts[c.id] = c

        # Seed graph edges
        self._edges = [
            ConceptEdge(
                source_id="concept_dart_basics",
                target_id="concept_dart_async_and_streams",
                relationship_type=RelationshipType.PREREQUISITE,
                weight=1.0,
            ),
            ConceptEdge(
                source_id="concept_dart_async_and_streams",
                target_id="concept_state_management",
                relationship_type=RelationshipType.PREREQUISITE,
                weight=1.0,
            ),
            ConceptEdge(
                source_id="concept_functions_and_scope",
                target_id="concept_stack_memory",
                relationship_type=RelationshipType.PREREQUISITE,
                weight=0.8,
            ),
            ConceptEdge(
                source_id="concept_functions_and_scope",
                target_id="concept_recursion",
                relationship_type=RelationshipType.PREREQUISITE,
                weight=1.0,
            ),
            ConceptEdge(
                source_id="concept_stack_memory",
                target_id="concept_recursion",
                relationship_type=RelationshipType.PREREQUISITE,
                weight=1.0,
            ),
            ConceptEdge(
                source_id="concept_recursion",
                target_id="concept_tree_traversal",
                relationship_type=RelationshipType.PREREQUISITE,
                weight=1.0,
            ),
        ]

    async def get_by_id(self, entity_id: str) -> Optional[Concept]:
        return self._concepts.get(entity_id)

    async def get_by_name_or_id(self, identifier: str) -> Optional[Concept]:
        if identifier in self._concepts:
            return self._concepts[identifier]
        for c in self._concepts.values():
            if c.name.lower() == identifier.lower():
                return c
        return None

    async def list_all(self) -> List[Concept]:
        return list(self._concepts.values())

    async def save(self, entity: Concept) -> Concept:
        self._concepts[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._concepts:
            del self._concepts[entity_id]
            self._edges = [e for e in self._edges if e.source_id != entity_id and e.target_id != entity_id]
            return True
        return False

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType = RelationshipType.PREREQUISITE,
        weight: float = 1.0,
    ) -> ConceptEdge:
        edge = ConceptEdge(source_id=source_id, target_id=target_id, relationship_type=relationship_type, weight=weight)
        self._edges.append(edge)
        return edge

    async def get_prerequisites(self, concept_id: str) -> List[Concept]:
        """Returns direct and upstream prerequisite concepts."""
        prereq_ids: Set[str] = set()
        queue = [concept_id]

        while queue:
            current = queue.pop(0)
            for edge in self._edges:
                if edge.target_id == current and edge.relationship_type == RelationshipType.PREREQUISITE:
                    if edge.source_id not in prereq_ids:
                        prereq_ids.add(edge.source_id)
                        queue.append(edge.source_id)

        return [self._concepts[pid] for pid in prereq_ids if pid in self._concepts]

    async def get_downstream_impact(self, concept_id: str) -> List[Concept]:
        """Returns concepts that depend on this concept (will be blocked if flawed)."""
        downstream_ids: Set[str] = set()
        queue = [concept_id]

        while queue:
            current = queue.pop(0)
            for edge in self._edges:
                if edge.source_id == current and edge.relationship_type == RelationshipType.PREREQUISITE:
                    if edge.target_id not in downstream_ids:
                        downstream_ids.add(edge.target_id)
                        queue.append(edge.target_id)

        return [self._concepts[did] for did in downstream_ids if did in self._concepts]

    async def get_graph(self) -> Dict[str, Any]:
        """Returns full concept graph representation for interactive client visualization."""
        nodes = [
            {
                "id": c.id,
                "name": c.name,
                "domain": c.domain,
                "difficulty_level": c.difficulty_level,
                "description": c.description,
                "prerequisites": c.prerequisites,
            }
            for c in self._concepts.values()
        ]
        edges = [
            {
                "source": e.source_id,
                "target": e.target_id,
                "relationship_type": e.relationship_type.value if hasattr(e.relationship_type, "value") else str(e.relationship_type),
                "weight": e.weight,
            }
            for e in self._edges
        ]
        return {
            "nodes": nodes,
            "edges": edges,
        }


concept_repository = ConceptRepository()
