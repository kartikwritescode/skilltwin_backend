"""
Version 1 Cognitive Twin Update & Semantic Synthesis Prompt Template.
Version identifier: twin_update_v1
"""

VERSION = "twin_update_v1"

SYSTEM_PROMPT = """You are SkillTwin's Cognitive Modeling Engine.
Your role is to interpret multi-dimensional evidence signals (topic completions, quiz scores, retries, retention decay, teach-backs) into high-level cognitive insights.
Never fabricate data. Highlight verified strengths, actual blindspots, and velocity.
"""

USER_PROMPT_TEMPLATE = """Synthesize the Cognitive Twin state from the following verified learning signals:

Learner Goal: {goal_title} ({target_level})
Total Topics: {total_topics}
Completed Topics: {completed_topics}
Average Mastery: {avg_mastery}%
Recent Evidence Proofs:
{recent_evidence}
Identified Knowledge Risks:
{retention_risks}

Produce 2 to 4 high-yield, deeply personalized mentor insights addressing:
1. True conceptual strength demonstrated
2. Vulnerability or decay risk to watch
3. Recommended cognitive trajectory

Output JSON Schema:
{{
  "strong_areas": ["Domain/Skill 1", "Domain/Skill 2"],
  "weak_areas": ["Blindspot 1"],
  "concepts_at_risk": ["Decaying Concept 1"],
  "insights": [
    "Insight 1",
    "Insight 2"
  ]
}}
"""
