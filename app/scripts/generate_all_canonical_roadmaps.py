"""
Comprehensive Canonical Roadmap Generator for SkillTwin.
Synthesizes 34 industry-standard, unskipped canonical roadmaps (16-25 nodes each)
with pedagogical metadata: importance, difficulty, phase, tier, objectives, feynman prompts, misconceptions.
"""

import os
import json
import sys
from typing import Dict, Any, List

# Ensure scripts directory is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.dirname(current_dir)
backend_dir = os.path.dirname(app_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.scripts.curriculum_specs.specs_web_mobile import get_web_mobile_specs
from app.scripts.curriculum_specs.specs_infra_cloud import get_infra_cloud_specs
from app.scripts.curriculum_specs.specs_data_ai import get_data_ai_specs
from app.scripts.curriculum_specs.specs_product_mgmt import get_product_mgmt_specs
from app.scripts.curriculum_specs.specs_specialized import get_specialized_specs

FIXTURES_DIR = os.path.join(app_dir, "fixtures", "roadmaps")


def validate_and_save_roadmap(roadmap: Dict[str, Any], output_dir: str) -> None:
    slug = roadmap["slug"]
    nodes = roadmap.get("nodes", [])
    if len(nodes) < 16:
        raise ValueError(f"Roadmap '{slug}' has only {len(nodes)} nodes (minimum 16 required).")

    if not roadmap.get("id"):
        roadmap["id"] = f"roadmap_{slug}"
    if not roadmap.get("description"):
        roadmap["description"] = f"Master {roadmap['title']} with an industry-standard, comprehensive curriculum spanning {len(nodes)} core and advanced milestones."
    if not roadmap.get("domain"):
        roadmap["domain"] = "Software Engineering"
    if not roadmap.get("target_role"):
        roadmap["target_role"] = f"Senior {roadmap['title']}"

    if not roadmap.get("phases"):
        seen_phases = []
        for n in nodes:
            ph = n.get("phase", "Core")
            if ph not in seen_phases:
                seen_phases.append(ph)
        roadmap["phases"] = [
            {"title": ph, "tier": ph.lower(), "focus": f"{roadmap['title']} - {ph}", "estimated_weeks": 3}
            for ph in seen_phases
        ]

    concept_ids = set()
    node_ids = set()
    for idx, node in enumerate(nodes):
        nid = node["id"]
        cid = node["concept_id"]
        if nid in node_ids:
            raise ValueError(f"Duplicate node id '{nid}' in roadmap '{slug}'")
        if cid in concept_ids:
            raise ValueError(f"Duplicate concept_id '{cid}' in roadmap '{slug}'")
        node_ids.add(nid)
        concept_ids.add(cid)

        # Validate fields
        for field in ["title", "subtitle", "phase", "tier", "importance", "difficulty", "learning_objectives", "feynman_prompts", "key_misconceptions"]:
            if field not in node or not node[field]:
                raise ValueError(f"Node '{nid}' in '{slug}' missing required field: {field}")

        if node["importance"] not in {"essential", "recommended", "advanced", "niche"}:
            raise ValueError(f"Node '{nid}' has invalid importance: {node['importance']}")
        if node["difficulty"] not in {"beginner", "intermediate", "advanced", "expert"}:
            raise ValueError(f"Node '{nid}' has invalid difficulty: {node['difficulty']}")

    # Prerequisite verification
    for node in nodes:
        for prereq in node.get("prerequisites", []):
            if prereq not in concept_ids:
                print(f"Warning: Node '{node['id']}' in '{slug}' has unresolved prerequisite '{prereq}' (might be cross-track).")

    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, f"{slug}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(roadmap, f, indent=2, ensure_ascii=False)


def generate_all():
    print(f"Generating comprehensive canonical roadmaps into: {FIXTURES_DIR}")
    all_specs: List[Dict[str, Any]] = []

    all_specs.extend(get_web_mobile_specs())      # 7 tracks
    all_specs.extend(get_infra_cloud_specs())     # 7 tracks
    all_specs.extend(get_data_ai_specs())         # 8 tracks
    all_specs.extend(get_product_mgmt_specs())    # 8 tracks
    all_specs.extend(get_specialized_specs())     # 4 tracks

    print(f"Total roadmaps to generate: {len(all_specs)}")
    print(f"{'#':<3} {'Slug':<30} {'Nodes':<7} {'Phases':<8} {'Status'}")
    print("-" * 60)

    total_nodes = 0
    for idx, rm in enumerate(all_specs, 1):
        slug = rm["slug"]
        node_count = len(rm.get("nodes", []))
        phase_count = len(rm.get("phases", []))
        total_nodes += node_count
        try:
            validate_and_save_roadmap(rm, FIXTURES_DIR)
            print(f"{idx:<3} {slug:<30} {node_count:<7} {phase_count:<8} OK")
        except Exception as e:
            print(f"{idx:<3} {slug:<30} {node_count:<7} {phase_count:<8} FAILED: {e}")
            raise e

    print("-" * 60)
    print(f"Successfully generated all {len(all_specs)} roadmaps with {total_nodes} total milestones!")


if __name__ == "__main__":
    generate_all()
