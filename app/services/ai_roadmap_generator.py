"""
AI-Powered Roadmap Generator for SkillTwin.
Uses static JSON roadmaps as reference templates and Gemini AI to generate
personalized, context-aware roadmaps based on user inputs.
"""

import json
import os
from typing import Dict, Any, List, Optional
from app.core.logging import logger
from app.ai.providers.factory import get_llm_provider
from app.ai.providers.base import LLMProvider


class AIRoadmapGenerator:
    """
    Generates personalized roadmaps using AI by referencing static templates.
    Takes user inputs (domain, role, experience level, goals) and synthesizes
    a tailored roadmap following the canonical structure.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider or get_llm_provider()
        self._template_cache: Dict[str, Dict[str, Any]] = {}
        self._templates_loaded = False

    def _get_fixtures_dir(self) -> str:
        """Get the path to roadmap fixtures directory."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "fixtures", "roadmaps")

    async def _load_template_references(self) -> None:
        """Load all static JSON roadmaps to use as reference templates."""
        if self._templates_loaded:
            return

        fixtures_dir = self._get_fixtures_dir()
        if not os.path.exists(fixtures_dir):
            logger.warning(f"Roadmap templates directory not found: {fixtures_dir}")
            return

        json_files = [f for f in os.listdir(fixtures_dir) if f.endswith(".json")]
        logger.info(f"Loading {len(json_files)} roadmap templates for AI reference")

        for fname in json_files:
            file_path = os.path.join(fixtures_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    slug = data.get("slug", fname.replace(".json", ""))
                    self._template_cache[slug] = data
            except Exception as e:
                logger.error(f"Failed to load template '{fname}': {e}")

        self._templates_loaded = True
        logger.info(f"Loaded {len(self._template_cache)} roadmap templates")

    def _get_relevant_templates(self, domain: str, tags: List[str]) -> List[Dict[str, Any]]:
        """
        Find the most relevant template roadmaps based on domain and tags.
        Returns up to 3 matching templates for AI reference.
        """
        matches = []
        domain_lower = domain.lower()
        tags_lower = [t.lower() for t in tags]

        for template in self._template_cache.values():
            template_domain = template.get("domain", "").lower()
            template_tags = [t.lower() for t in template.get("tags", [])]

            # Calculate relevance score
            score = 0
            if domain_lower in template_domain or template_domain in domain_lower:
                score += 10

            for tag in tags_lower:
                if tag in template_tags or any(tag in tt for tt in template_tags):
                    score += 2

            if score > 0:
                matches.append((score, template))

        # Sort by score and return top 3
        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches[:3]]

    def _build_generation_prompt(
        self,
        domain: str,
        target_role: str,
        difficulty_baseline: str,
        tags: List[str],
        reference_templates: List[Dict[str, Any]],
        user_goals: Optional[str] = None,
        specializations: Optional[List[str]] = None,
    ) -> str:
        """Build the comprehensive prompt for AI roadmap generation."""

        # Format reference templates for the prompt
        template_examples = []
        for idx, template in enumerate(reference_templates[:2], 1):
            # Include 2-3 sample nodes from each template
            sample_nodes = template.get("nodes", [])[:3]
            template_examples.append(f"""
Example {idx}: {template.get('title')} ({template.get('slug')})
Domain: {template.get('domain')}
Target Role: {template.get('target_role')}
Sample Node Structure:
{json.dumps(sample_nodes[0] if sample_nodes else {}, indent=2)}
""")

        specializations_text = ""
        if specializations:
            specializations_text = f"\nSpecializations to emphasize: {', '.join(specializations)}"

        goals_text = ""
        if user_goals:
            goals_text = f"\nUser's specific goals: {user_goals}"

        prompt = f"""You are an expert curriculum designer for SkillTwin, a personalized learning platform.

Your task is to generate a comprehensive learning roadmap following our exact JSON structure.

**Target Roadmap Requirements:**
- Domain: {domain}
- Target Role: {target_role}
- Difficulty Baseline: {difficulty_baseline}
- Tags: {', '.join(tags)}{specializations_text}{goals_text}

**Reference Templates:**
{chr(10).join(template_examples)}

**Critical Requirements:**
1. Generate 16-25 nodes (learning milestones)
2. Each node MUST have ALL these fields:
   - id: "cnode_{{domain}}_{{concept_name}}" (unique identifier)
   - concept_id: "concept_{{domain}}_{{concept_name}}" (unique concept ID)
   - title: Clear, actionable title
   - subtitle: Detailed technical breakdown (tools, frameworks, specific skills)
   - phase: One of ["Foundations", "Core", "Advanced", "Specialization"]
   - tier: One of ["foundation", "intermediate", "advanced", "expert"]
   - importance: One of ["essential", "recommended", "advanced", "niche"]
   - difficulty: One of ["beginner", "intermediate", "advanced", "expert"]
   - order: Sequential number starting from 1
   - estimated_minutes: Realistic time estimate (20-40 minutes typical)
   - prerequisites: Array of concept_ids this depends on
   - learning_objectives: Array of 2-3 specific, measurable objectives
   - feynman_prompts: Array of 1-2 thought-provoking questions
   - key_misconceptions: Array of 1-2 common misunderstandings to address
   - recommended_resources: Empty array [] (we populate this separately)

3. Node ordering must be pedagogically sound:
   - Start with foundations
   - Build complexity progressively
   - Respect prerequisite dependencies

4. Phase distribution guidelines:
   - Foundations: 20-30% (basics, fundamentals)
   - Core: 40-50% (main skills and patterns)
   - Advanced: 20-30% (optimization, architecture)
   - Specialization: 10-20% (niche, cutting-edge topics)

5. Difficulty distribution for {difficulty_baseline} baseline:
   - Beginner: 40% beginner, 40% intermediate, 15% advanced, 5% expert
   - Intermediate: 20% beginner, 40% intermediate, 30% advanced, 10% expert
   - Advanced: 10% beginner, 30% intermediate, 40% advanced, 20% expert

6. Importance balance:
   - essential: 50-60% (must-know core concepts)
   - recommended: 25-30% (important for competency)
   - advanced: 10-15% (optimization, best practices)
   - niche: 5-10% (specialized, cutting-edge)

**Output Format:**
Return ONLY valid JSON matching this structure:
{{
  "slug": "{{domain_slug}}",
  "title": "{target_role}",
  "domain": "{domain}",
  "target_role": "{target_role}",
  "difficulty_baseline": "{difficulty_baseline}",
  "tags": {json.dumps(tags)},
  "nodes": [
    // Array of 16-25 nodes following the structure above
  ]
}}

Generate a world-class, industry-standard roadmap now. Output ONLY the JSON, no markdown formatting or explanation."""

        return prompt

    async def generate_roadmap(
        self,
        domain: str,
        target_role: str,
        difficulty_baseline: str = "Beginner",
        tags: Optional[List[str]] = None,
        user_goals: Optional[str] = None,
        specializations: Optional[List[str]] = None,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Generate a personalized roadmap using AI with reference templates.

        Args:
            domain: The learning domain (e.g., "Frontend Development", "Data Science")
            target_role: The target job role (e.g., "Senior Frontend Engineer")
            difficulty_baseline: Starting difficulty level
            tags: List of relevant tags/keywords
            user_goals: Optional specific user goals or context
            specializations: Optional list of areas to emphasize
            temperature: AI temperature (0.0-1.0, higher = more creative)

        Returns:
            Dict containing the generated roadmap in canonical format
        """
        await self._load_template_references()

        tags = tags or []
        if not tags:
            # Generate tags from domain and role
            tags = [
                domain.lower().replace(" ", "_"),
                target_role.lower().replace(" ", "_"),
            ]

        # Find relevant reference templates
        reference_templates = self._get_relevant_templates(domain, tags)

        if not reference_templates:
            logger.warning(f"No matching templates found for domain: {domain}")
            # Use any 2 templates as general reference
            reference_templates = list(self._template_cache.values())[:2]

        logger.info(
            f"Generating roadmap for '{target_role}' in '{domain}' "
            f"using {len(reference_templates)} reference templates"
        )

        # Build the prompt
        prompt = self._build_generation_prompt(
            domain=domain,
            target_role=target_role,
            difficulty_baseline=difficulty_baseline,
            tags=tags,
            reference_templates=reference_templates,
            user_goals=user_goals,
            specializations=specializations,
        )

        # Generate using AI
        try:
            response = await self.llm_provider.generate_text(
                prompt=prompt,
                temperature=temperature,
                max_tokens=8000,  # Need large context for full roadmap
            )

            # Parse JSON response
            # Remove markdown code blocks if present
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                if response.startswith("json"):
                    response = response[4:].strip()

            roadmap_data = json.loads(response)

            # Validate basic structure
            if "nodes" not in roadmap_data or not isinstance(roadmap_data["nodes"], list):
                raise ValueError("Generated roadmap missing 'nodes' array")

            node_count = len(roadmap_data["nodes"])
            if node_count < 16:
                logger.warning(f"Generated roadmap has only {node_count} nodes (minimum 16)")

            # Add metadata
            roadmap_data["id"] = f"roadmap_{roadmap_data.get('slug', 'custom')}"
            roadmap_data["description"] = (
                roadmap_data.get("description") or
                f"AI-generated personalized roadmap for {target_role} in {domain} "
                f"with {node_count} milestones."
            )

            logger.info(
                f"Successfully generated roadmap '{roadmap_data.get('title')}' "
                f"with {node_count} nodes"
            )

            return roadmap_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.debug(f"Response text: {response[:500]}...")
            raise ValueError(f"AI generated invalid JSON: {str(e)}")

        except Exception as e:
            logger.error(f"Roadmap generation failed: {e}", exc_info=True)
            raise

    async def refine_existing_roadmap(
        self,
        existing_roadmap: Dict[str, Any],
        refinement_instructions: str,
        temperature: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Refine an existing roadmap based on user feedback or instructions.

        Args:
            existing_roadmap: The current roadmap JSON
            refinement_instructions: What to change or improve
            temperature: AI temperature for refinement

        Returns:
            Refined roadmap
        """
        prompt = f"""You are refining an existing learning roadmap for SkillTwin.

**Current Roadmap:**
```json
{json.dumps(existing_roadmap, indent=2)}
```

**Refinement Instructions:**
{refinement_instructions}

**Requirements:**
1. Maintain the same JSON structure and all required fields
2. Keep the same number of nodes unless explicitly asked to add/remove
3. Preserve node IDs and concept_ids unless restructuring
4. Apply the requested changes thoughtfully
5. Ensure pedagogical coherence after changes

Return the complete refined roadmap as valid JSON, no markdown formatting."""

        try:
            response = await self.llm_provider.generate_text(
                prompt=prompt,
                temperature=temperature,
                max_tokens=8000,
            )

            # Parse response
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                if response.startswith("json"):
                    response = response[4:].strip()

            refined_roadmap = json.loads(response)

            logger.info(
                f"Successfully refined roadmap '{refined_roadmap.get('title')}' "
                f"with instructions: {refinement_instructions[:100]}"
            )

            return refined_roadmap

        except Exception as e:
            logger.error(f"Roadmap refinement failed: {e}", exc_info=True)
            raise


# Singleton instance
ai_roadmap_generator = AIRoadmapGenerator()
