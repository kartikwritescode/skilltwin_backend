import pytest
import uuid
from sqlalchemy import select, func
from app.core.database import get_session_factory, init_db
from app.core.db_models import CanonicalOntologyModel, MicroSubgraphModel
from app.schemas.adaptive_path import MicroSubgraphCreate
from app.services.canonical_registry_service import canonical_registry_service


@pytest.mark.asyncio
async def test_canonical_registry_seeding_and_invariants():
    """Verify seeding yields 50+ subgraphs and satisfies prerequisite invariants."""
    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        ont_count, sg_count = await canonical_registry_service.seed_canonical_subgraphs_if_empty(session)
        assert ont_count >= 30, f"Expected at least 30 ontologies, found {ont_count}"
        assert sg_count >= 50, f"Expected at least 50 micro-subgraphs, found {sg_count}"

        # Test breakdown across core domains
        domains = ["Frontend", "Backend", "Machine Learning", "DevOps", "Mobile"]
        for domain in domains:
            domain_sgs = await canonical_registry_service.find_subgraphs_by_domain(domain, session)
            assert len(domain_sgs) > 0, f"Expected subgraphs for domain '{domain}', found 0"

        # Test prerequisite invariant: every non-foundational canonical subgraph MUST have prerequisites
        non_foundational_stmt = select(MicroSubgraphModel).where(
            MicroSubgraphModel.ontology_id.isnot(None),
            MicroSubgraphModel.tier != "foundational",
        )
        non_foundational = (await session.execute(non_foundational_stmt)).scalars().all()
        assert len(non_foundational) > 0

        for sg in non_foundational:
            assert len(sg.prerequisites) > 0, f"Micro-subgraph '{sg.slug}' is non-foundational but has no prerequisites"


@pytest.mark.asyncio
async def test_find_subgraph_by_slug():
    """Verify lookup of specific canonical subgraphs by slug."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Find any existing subgraph
        sample_sg = (await session.execute(select(MicroSubgraphModel).limit(1))).scalar_one()
        assert sample_sg is not None

        found = await canonical_registry_service.find_subgraph_by_slug(sample_sg.slug, session)
        assert found is not None
        assert found.id == sample_sg.id
        assert found.title == sample_sg.title


@pytest.mark.asyncio
async def test_search_subgraphs_semantic_react():
    """Verify semantic and lexical search retrieves relevant micro-subgraphs."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Search for React & State Management
        results = await canonical_registry_service.search_subgraphs_semantic(
            query="Learn React and State Management",
            limit=5,
            threshold=0.50,
            session=session,
        )
        assert len(results) > 0, "Expected search results for 'Learn React and State Management'"

        # Verify that top results relate to frontend or web
        titles_and_slugs = " ".join([f"{r.slug} {r.title}" for r in results]).lower()
        assert "front" in titles_and_slugs or "web" in titles_and_slugs or "react" in titles_and_slugs


@pytest.mark.asyncio
async def test_register_novel_subgraph():
    """Verify registering a novel micro-subgraph for 0-token reuse."""
    session_factory = get_session_factory()
    novel_slug = f"novel-quantum-computing-{uuid.uuid4().hex[:6]}"

    async with session_factory() as session:
        subgraph_in = MicroSubgraphCreate(
            slug=novel_slug,
            title="Quantum Circuit Synthesis & Qubits",
            tier="advanced",
            estimated_minutes=75,
            prerequisites=["linear-algebra-foundations"],
        )
        created = await canonical_registry_service.register_novel_subgraph(subgraph_in, session)
        assert created.slug == novel_slug
        assert created.tier == "advanced"
        assert created.estimated_minutes == 75

        # Query back
        retrieved = await canonical_registry_service.find_subgraph_by_slug(novel_slug, session)
        assert retrieved is not None
        assert retrieved.title == "Quantum Circuit Synthesis & Qubits"
        assert retrieved.prerequisites == ["linear-algebra-foundations"]
