import os
import sys
import asyncio
import argparse
from pathlib import Path
from sqlalchemy import select, func

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.logging import logger
from app.core.database import init_db, get_session_factory
from app.core.db_models import CanonicalOntologyModel, MicroSubgraphModel
from app.services.canonical_registry_service import canonical_registry_service


async def main():
    parser = argparse.ArgumentParser(description="Seed Canonical Micro-Subgraphs into SkillTwin DB")
    parser.add_argument("--force", action="store_true", help="Force re-seeding even if database already populated")
    parser.add_argument("--fixtures-dir", type=str, default=None, help="Custom path to roadmap JSON fixtures")
    args = parser.parse_args()

    print("\n=======================================================")
    print(" [*] Initializing Canonical Micro-Subgraph Seeder")
    print("=======================================================")

    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        ont_count, sg_count = await canonical_registry_service.seed_canonical_subgraphs_if_empty(
            session=session,
            fixtures_dir=args.fixtures_dir,
            force=args.force,
        )

        # Retrieve summary metrics
        ont_total = (await session.execute(select(func.count(CanonicalOntologyModel.id)))).scalar_one()
        sg_total = (await session.execute(select(func.count(MicroSubgraphModel.id)))).scalar_one()

        # Breakdown by tier
        tier_query = select(MicroSubgraphModel.tier, func.count(MicroSubgraphModel.id)).group_by(MicroSubgraphModel.tier)
        tier_counts = dict((await session.execute(tier_query)).all())

        print(f"\n[OK] Seeding Complete!")
        print(f" - Canonical Ontologies in DB : {ont_total}")
        print(f" - Micro-Subgraphs in DB      : {sg_total}")
        print("\n[*] Micro-Subgraphs Breakdown by Tier:")
        for tier, count in tier_counts.items():
            print(f"   - {tier.upper():<14}: {count} subgraphs")

        # Verify prerequisite invariant
        non_foundational_query = select(MicroSubgraphModel).where(MicroSubgraphModel.tier != "foundational")
        non_foundational_sgs = (await session.execute(non_foundational_query)).scalars().all()
        invalid_count = sum(1 for sg in non_foundational_sgs if not sg.prerequisites)

        print(f"\n[*] Prerequisite Integrity Check:")
        print(f"   - Non-foundational subgraphs evaluated: {len(non_foundational_sgs)}")
        print(f"   - Subgraphs missing prerequisites     : {invalid_count}")

        if invalid_count == 0:
            print("   - Invariant PASS: 100% of non-foundational subgraphs have valid prerequisites!\n")
        else:
            print(f"   - Warning: {invalid_count} subgraphs have empty prerequisites.\n")

    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())
