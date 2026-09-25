import os
import re
import json
import math
import uuid
from typing import Optional, List, Dict, Tuple, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.core.database import get_session_factory
from app.core.db_models import CanonicalOntologyModel, MicroSubgraphModel
from app.schemas.adaptive_path import MicroSubgraphCreate
from app.services.embedding_service import EmbeddingService, embedding_service


class CanonicalRegistryService:
    """
    Manages Canonical Knowledge Ontologies and composable Micro-Subgraphs
    for deterministic, 0-token curriculum assembly and fast semantic retrieval.
    """

    def __init__(self, embedder: Optional[EmbeddingService] = None):
        self.embedder = embedder or embedding_service
        self._cached_ontologies: Dict[str, CanonicalOntologyModel] = {}

    def _slugify(self, text: str) -> str:
        """Converts arbitrary text into a clean alphanumeric kebab-case slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"[\s_]+", "-", text).strip("-")

    async def seed_canonical_subgraphs_if_empty(
        self,
        session: Optional[AsyncSession] = None,
        fixtures_dir: Optional[str] = None,
        force: bool = False,
    ) -> Tuple[int, int]:
        """
        Parses all 34 domain roadmaps and extracts standardized 3-to-5 node
        micro-subgraphs with prerequisite slugs into the database.
        Returns: (ontologies_count, subgraphs_count)
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.seed_canonical_subgraphs_if_empty(sess, fixtures_dir, force)

        # Check existing count
        count_res = await session.execute(select(func.count(MicroSubgraphModel.id)))
        existing_count = count_res.scalar_one() or 0
        if existing_count >= 50 and not force:
            logger.info(f"Canonical subgraphs already populated ({existing_count} present). Skipping seed.")
            ont_count_res = await session.execute(select(func.count(CanonicalOntologyModel.id)))
            ont_count = ont_count_res.scalar_one() or 0
            return ont_count, existing_count

        if not fixtures_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            fixtures_dir = os.path.join(base_dir, "fixtures", "roadmaps")

        if not os.path.exists(fixtures_dir):
            logger.warning(f"Canonical roadmaps fixtures directory not found at: {fixtures_dir}")
            return 0, 0

        json_files = sorted([f for f in os.listdir(fixtures_dir) if f.endswith(".json")])
        logger.info(f"Seeding canonical ontologies and micro-subgraphs from {len(json_files)} fixtures...")

        total_ontologies = 0
        total_subgraphs = 0

        for fname in json_files:
            file_path = os.path.join(fixtures_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                slug = data.get("slug") or self._slugify(data["title"])
                ontology_id = f"ontology_{slug}"
                title = data["title"]
                domain = data.get("domain", "Software Engineering")
                description = data.get("description", f"Canonical curriculum for {title}")
                tags = data.get("tags", [])
                nodes = data.get("nodes", [])

                # Generate or fetch embedding
                embed_text = f"{title} {domain} {' '.join(tags)}"
                embedding = data.get("embedding")
                if not embedding:
                    embedding = await self.embedder.embed_query(embed_text)

                # Store domain tags in description so ontologies retain full keyword index
                tag_str = ", ".join(tags)
                full_description = f"{description} | Tags: {tag_str}" if tag_str else description

                # Upsert CanonicalOntologyModel
                existing_ont = await session.get(CanonicalOntologyModel, ontology_id)
                if not existing_ont:
                    ontology = CanonicalOntologyModel(
                        id=ontology_id,
                        domain=domain,
                        title=title,
                        description=full_description,
                        embedding=embedding,
                        total_nodes=len(nodes),
                    )
                    session.add(ontology)
                    await session.flush()
                else:
                    existing_ont.domain = domain
                    existing_ont.title = title
                    existing_ont.description = full_description
                    existing_ont.embedding = embedding
                    existing_ont.total_nodes = len(nodes)
                    ontology = existing_ont

                total_ontologies += 1

                # Decompose roadmap nodes into 3-to-5 node composable micro-subgraphs
                subgraph_groups = self._decompose_nodes_into_subgraph_groups(slug, title, nodes)
                prev_subgraph_slug: Optional[str] = None

                for idx, group in enumerate(subgraph_groups):
                    sg_slug = group["slug"]
                    tier = group["tier"]

                    # Link prerequisites
                    if idx == 0:
                        prerequisites = []
                        tier = "foundational"
                    else:
                        prerequisites = [prev_subgraph_slug] if prev_subgraph_slug else []

                    existing_sg = await session.get(MicroSubgraphModel, f"subgraph_{sg_slug}")
                    if not existing_sg:
                        sg_model = MicroSubgraphModel(
                            id=f"subgraph_{sg_slug}",
                            ontology_id=ontology_id,
                            slug=sg_slug,
                            title=group["title"],
                            tier=tier,
                            estimated_minutes=group["estimated_minutes"],
                            prerequisites=prerequisites,
                        )
                        session.add(sg_model)
                    else:
                        existing_sg.title = group["title"]
                        existing_sg.tier = tier
                        existing_sg.estimated_minutes = group["estimated_minutes"]
                        existing_sg.prerequisites = prerequisites

                    prev_subgraph_slug = sg_slug
                    total_subgraphs += 1

            except Exception as e:
                logger.error(f"Error parsing fixture '{fname}': {e}", exc_info=True)

        await session.commit()
        logger.info(f"Seeding completed successfully: {total_ontologies} ontologies, {total_subgraphs} micro-subgraphs.")
        return total_ontologies, total_subgraphs

    def _decompose_nodes_into_subgraph_groups(
        self, roadmap_slug: str, roadmap_title: str, nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Decomposes a list of nodes into coherent 3-to-5 node micro-subgraph clusters.
        Groups by phase where possible, maintaining order and sizing bounds.
        """
        if not nodes:
            return []

        # Group by phase preserving sequential order
        phase_map: Dict[str, List[Dict[str, Any]]] = {}
        for n in nodes:
            phase = n.get("phase", "General Core").strip()
            if phase not in phase_map:
                phase_map[phase] = []
            phase_map[phase].append(n)

        subgraph_groups: List[Dict[str, Any]] = []

        for phase_name, p_nodes in phase_map.items():
            # If a phase is too large (> 5 nodes), chunk it into groups of 3-4
            chunk_size = 4
            chunks = [p_nodes[i : i + chunk_size] for i in range(0, len(p_nodes), chunk_size)]

            for c_idx, chunk in enumerate(chunks):
                part_suffix = f"-part-{c_idx + 1}" if len(chunks) > 1 else ""
                clean_phase = self._slugify(phase_name)
                sg_slug = f"{roadmap_slug}-{clean_phase}{part_suffix}"

                # Calculate estimated minutes
                total_mins = sum(n.get("estimated_minutes", 25) for n in chunk)
                total_mins = max(30, min(total_mins, 180))

                # Determine tier
                lower_phase = phase_name.lower()
                if "foundation" in lower_phase or "basic" in lower_phase:
                    tier = "foundational"
                elif "advanc" in lower_phase or "mastery" in lower_phase:
                    tier = "advanced"
                elif "product" in lower_phase or "elect" in lower_phase or "deploy" in lower_phase:
                    tier = "elective"
                else:
                    tier = "core"

                # Extract key concept highlight for descriptive title
                concept_titles = [n.get("title", "").split(":")[0].strip() for n in chunk if n.get("title")]
                highlight = f": {concept_titles[0]}" if concept_titles else ""
                part_label = f" (Part {c_idx + 1})" if len(chunks) > 1 else ""
                sg_title = f"{roadmap_title}: {phase_name}{part_label}{highlight}"

                subgraph_groups.append({
                    "slug": sg_slug,
                    "title": sg_title,
                    "tier": tier,
                    "estimated_minutes": total_mins,
                    "nodes": chunk,
                })

        return subgraph_groups

    async def find_subgraphs_by_domain(
        self, domain: str, session: AsyncSession
    ) -> List[MicroSubgraphModel]:
        """Returns all micro-subgraphs belonging to an ontology matching the given domain."""
        query = (
            select(MicroSubgraphModel)
            .join(CanonicalOntologyModel, MicroSubgraphModel.ontology_id == CanonicalOntologyModel.id)
            .where(CanonicalOntologyModel.domain.ilike(f"%{domain}%"))
            .order_by(MicroSubgraphModel.created_at)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    async def find_subgraph_by_slug(
        self, slug: str, session: AsyncSession
    ) -> Optional[MicroSubgraphModel]:
        """Look up a single micro-subgraph by unique slug."""
        query = select(MicroSubgraphModel).where(MicroSubgraphModel.slug == slug)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def search_subgraphs_semantic(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.50,
        fallback_to_synthesis: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[MicroSubgraphModel]:
        """
        Hybrid semantic and lexical search:
        Calculates cosine similarity of query embedding with ontologies,
        combined with lexical tag and title overlap on micro-subgraphs.
        Returns top matching subgraphs. If no matches found and fallback_to_synthesis=True,
        dynamically synthesizes and indexes a novel micro-subgraph.
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.search_subgraphs_semantic(
                    query, limit, threshold, fallback_to_synthesis, sess
                )

        # Ensure subgraphs are seeded
        await self.seed_canonical_subgraphs_if_empty(session)

        query_emb = await self.embedder.embed_query(query)
        norm_q = math.sqrt(sum(x * x for x in query_emb)) if query_emb else 0.0

        query_tokens = set(re.findall(r"\w+", query.lower())) - {"and", "the", "for", "with", "a", "an", "learn"}

        # Load all subgraphs with their parent ontology
        stmt = select(MicroSubgraphModel).options(selectinload(MicroSubgraphModel.ontology))
        result = await session.execute(stmt)
        all_subgraphs = list(result.scalars().all())

        scored: List[Tuple[MicroSubgraphModel, float]] = []

        for sg in all_subgraphs:
            ont = sg.ontology
            cos_score = 0.0

            # 1. Vector Cosine Similarity against parent ontology embedding
            if norm_q > 0.0 and ont and ont.embedding:
                ont_emb = ont.embedding
                norm_o = math.sqrt(sum(y * y for y in ont_emb))
                if norm_o > 0.0:
                    dot = sum(a * b for a, b in zip(query_emb, ont_emb))
                    cos_score = max(0.0, dot / (norm_q * norm_o))

            # 2. Lexical & Token Overlap
            searchable_text = f"{sg.title} {sg.slug} {ont.title if ont else ''} {ont.domain if ont else ''} {ont.description if ont else ''}".lower()
            target_tokens = set(re.findall(r"\w+", searchable_text))

            lex_score = 0.0
            if query_tokens and target_tokens:
                matched_tokens = query_tokens & target_tokens
                overlap = len(matched_tokens)
                lex_score = overlap / max(1, len(query_tokens))

                # Exact topic keyword groundings
                if "react" in query_tokens and ("react" in target_tokens or "frontend" in target_tokens):
                    lex_score = max(lex_score, 0.85)
                elif "flutter" in query_tokens and ("flutter" in target_tokens or "dart" in target_tokens):
                    lex_score = max(lex_score, 0.85)
                elif "python" in query_tokens and "python" in target_tokens:
                    lex_score = max(lex_score, 0.85)
                elif "devops" in query_tokens and ("devops" in target_tokens or "docker" in target_tokens):
                    lex_score = max(lex_score, 0.85)

            # Combined Hybrid Score
            if norm_q > 0.0 and cos_score > 0.0:
                hybrid_score = 0.5 * cos_score + 0.5 * min(1.0, lex_score)
                if lex_score >= 0.70:
                    hybrid_score = max(hybrid_score, 0.80)
            else:
                hybrid_score = lex_score

            if hybrid_score >= threshold:
                scored.append((sg, hybrid_score))

        # Fallback to Novel Subgraph Synthesis if empty and requested
        if not scored and fallback_to_synthesis:
            from app.services.novel_subgraph_synthesizer import novel_subgraph_synthesizer
            logger.info(
                f"[CanonicalRegistryService] No matching subgraphs for '{query}' above {threshold}. "
                f"Triggering novel synthesis fallback..."
            )
            novel_sg = await novel_subgraph_synthesizer.synthesize_micro_subgraph(query, session=session)
            return [novel_sg]

        # Sort descending by score
        scored.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored[:limit]]

    async def register_novel_subgraph(
        self, subgraph_data: MicroSubgraphCreate, session: AsyncSession
    ) -> MicroSubgraphModel:
        """
        Inserts a newly synthesized micro-subgraph into the global registry
        for perpetual 0-token reuse across all future learners.
        """
        sg_id = subgraph_data.id or f"subgraph_{subgraph_data.slug}"

        # Check existing
        existing = await session.get(MicroSubgraphModel, sg_id)
        if existing:
            return existing

        new_subgraph = MicroSubgraphModel(
            id=sg_id,
            ontology_id=subgraph_data.ontology_id,
            slug=subgraph_data.slug,
            title=subgraph_data.title,
            tier=subgraph_data.tier,
            estimated_minutes=subgraph_data.estimated_minutes,
            prerequisites=subgraph_data.prerequisites,
        )
        session.add(new_subgraph)
        await session.commit()
        await session.refresh(new_subgraph)
        logger.info(f"Registered novel micro-subgraph: [{new_subgraph.slug}] '{new_subgraph.title}'")
        return new_subgraph


canonical_registry_service = CanonicalRegistryService()
