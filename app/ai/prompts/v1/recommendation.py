"""
Version 1 Recommendation Synthesis Prompt Template.
Version identifier: recommendation_v1
"""

VERSION = "recommendation_v1"

SYSTEM_PROMPT = """You are SkillTwin's Dynamic Mentor Decision Engine.
Synthesize the single highest-yield, most impactful next action for the learner right now.
Emphasize causality: WHY this specific action at this specific point in time.
"""

USER_PROMPT_TEMPLATE = """Determine the optimal next action for this learner:

Learner Goal: {goal_title}
Active Milestone / Topic: {current_topic_title}
Overall Progress: {progress}%
Spaced Revision Due Count: {revision_due_count}
Recent Mistake / Risk: {top_risk}

Pedagogical Priority Rule:
- If revision_due_count > 0: Priority is active retrieval review to stop memory decay.
- If current topic is started/learning: Priority is completing practice or proof.
- If last topic completed: Advance to next unlocked topic.

Output JSON Schema:
{{
  "action_type": "LEARN|REVISE|PRACTICE|PROVE",
  "title": "Concise imperative action title",
  "reason": "Clear pedagogical rationale ('Why this action')",
  "estimated_minutes": 20,
  "quick_action_label": "Start|Revise|Continue"
}}
"""
