import asyncio
import argparse
import sys
from app.core.logging import logger
from app.services.canonical_roadmap_service import canonical_roadmap_service


async def main():
    parser = argparse.ArgumentParser(description="Seed Canonical Roadmaps into SkillTwin DB")
    parser.add_argument("--dry-run", action="store_true", help="Validate fixtures without persistence")
    args = parser.parse_args()

    logger.info("Initializing Canonical Roadmap Seed Pipeline...")
    await canonical_roadmap_service.ensure_fixtures_loaded()

    roadmaps = await canonical_roadmap_service.canonical_repo.list_all()
    print(f"\n=======================================================")
    print(f" Successfully loaded {len(roadmaps)} Canonical Technology Roadmaps")
    print(f"=======================================================")
    for r in roadmaps:
        print(f" • [{r.slug.upper()}] {r.title}")
        print(f"    - Domain: {r.domain} | Nodes: {len(r.nodes)} | Est: {r.estimated_hours}h")
        print(f"    - Tags: {', '.join(r.tags[:4])}...")
    print(f"=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())
