import math
import hashlib
from typing import TypeVar, Type, Optional, List, Dict, Any
from pydantic import BaseModel

from app.ai.providers.base import LLMProvider
from app.ai.schemas.ai_schemas import (
    GeneratedJourneyPlan,
    GeneratedJourneyNode,
    GeneratedJourneyEdge,
    GeneratedSessionPlan,
    GeneratedSessionStep,
    ExtractedConcept,
    ExtractedConceptList,
    EvaluationResult,
    StepEvaluation,
    MentorDecisionAIOutput,
    MentorRecommendationOutput,
    MentorChatAIOutput,
    PersonalizedStudyNotesAIOutput,
    TeachEvaluationAIOutput,
)
from app.core.logging import logger

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider(LLMProvider):
    """
    Mock AI Provider enabling deterministic, offline local execution and fast automated testing.
    Produces high-fidelity synthetic pedagogical curricula and evaluations.
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> str:
        logger.debug(f"[MockLLM] generate_text invoked with prompt preview: {prompt[:80]}...")
        if "mentor" in prompt.lower() or "today" in prompt.lower():
            return (
                "Welcome back! Based on your recent evidence, your foundation in async pipelines "
                "is solid, but we should reinforce error handling before moving to distributed state."
            )
        return (
            "Here is your focused mentor advice: break down the problem into smaller invariant properties, "
            "implement the core logic first, and verify with boundary cases."
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        **kwargs
    ) -> T:
        logger.debug(f"[MockLLM] generate_structured requested for schema: {response_schema.__name__}")

        if response_schema == GeneratedJourneyPlan:
            # Deterministically synthesize an ordered winding roadmap
            goal_keywords = prompt.split()
            topic = "Core Mastery"
            if "flutter" in prompt.lower():
                topic = "Flutter Architecture"
                node_specs = [
                    ("Dart Async & Streams", "Understand StreamControllers, Futures, and microtask queues.", "Foundations"),
                    ("InheritedWidget & Scope", "Deep dive into widget tree context and element lifecycle.", "Architecture"),
                    ("State Management Architecture", "Master Riverpod / Bloc unidirectional data flow.", "Architecture"),
                    ("Custom RenderObjects", "Build custom layouts by understanding paint and performLayout protocols.", "Advanced"),
                    ("Platform Channels & FFI", "Bridge native Android/iOS C/Kotlin libraries with Dart.", "Mastery"),
                ]
            else:
                node_specs = [
                    (f"Foundations of {topic}", "Master core primitives, invariants, and mental models.", "Foundations"),
                    ("Architectural Design Patterns", "Deconstruct separation of concerns and data pipelines.", "Architecture"),
                    ("System Implementation", "Apply core mechanisms to real-world edge scenarios.", "Practice"),
                    ("Deep Diagnostics & Debugging", "Diagnose bottlenecks, race conditions, and state desync.", "Advanced"),
                    ("Capstone Production Proof", "Deliver end-to-end evidence under interview/real conditions.", "Mastery"),
                ]

            nodes: List[GeneratedJourneyNode] = []
            edges: List[GeneratedJourneyEdge] = []
            total_nodes = len(node_specs)

            for idx, (title, desc, phase) in enumerate(node_specs):
                # Calculate winding path coordinates for the visual Flutter winding roadmap
                # Sine wave creates alternating left/right curved path nodes
                pos_x = round(0.5 + 0.32 * math.sin(idx * 1.5), 3)
                pos_y = round(float(idx * 140.0), 1)

                nodes.append(
                    GeneratedJourneyNode(
                        title=title,
                        description=desc,
                        phase=phase,
                        order=idx + 1,
                        concept_name=title.lower().replace(" ", "_"),
                        estimated_minutes=25,
                        position_x=pos_x,
                        position_y=pos_y,
                    )
                )
                if idx > 0:
                    edges.append(
                        GeneratedJourneyEdge(
                            source_order=idx,
                            target_order=idx + 1,
                            edge_type="prerequisite"
                        )
                    )

            plan = GeneratedJourneyPlan(
                goal_title=prompt[:60],
                nodes=nodes,
                edges=edges,
                summary="Adaptive 5-stage mastery trajectory optimized for retention and proven evidence."
            )
            return plan  # type: ignore

        elif response_schema == GeneratedSessionPlan:
            # Deterministically synthesize structured session steps based on session type and concept
            p_lower = prompt.lower()
            concept_name = "Target Concept"
            if "recursion" in p_lower:
                concept_name = "Recursion & Base Cases"
            elif "stream" in p_lower or "async" in p_lower:
                concept_name = "Dart Async & Streams"

            if "remediate" in p_lower:
                sess_type = "REMEDIATE"
                title = f"Targeted Remediation: {concept_name}"
                pedagogical_focus = "Diagnose faulty base case models and reconstruct foundational mental models."
                steps = [
                    GeneratedSessionStep(
                        order=1,
                        step_type="DIAGNOSE",
                        title="Identify the Fault",
                        instruction="Examine the code snippet below and diagnose why the base case fails to terminate.",
                        prompt="Look at this recursive function: `def solve(n): return solve(n-1) if n > 0 else ...` What happens when `n < 0`?",
                        question_type="code_fix",
                        rubric_criteria="Must identify stack overflow or missing negative bound invariant."
                    ),
                    GeneratedSessionStep(
                        order=2,
                        step_type="EXPLAIN",
                        title="Articulate the Mechanism",
                        instruction="Explain in your own words how the call stack unwinds once the termination criterion is reached.",
                        prompt="How does the frame pointer return values back up the call chain?",
                        question_type="open_ended",
                        rubric_criteria="Must articulate stack unwinding and LIFO return order."
                    ),
                    GeneratedSessionStep(
                        order=3,
                        step_type="PRACTICE",
                        title="Reconstruct Invariant",
                        instruction="Rewrite the function to guarantee termination for all integers.",
                        prompt="Write the corrected base case condition.",
                        question_type="open_ended",
                        rubric_criteria="Correct boundary guard for n <= 0."
                    ),
                ]
            elif "prove" in p_lower:
                sess_type = "PROVE"
                title = f"Mastery Proof Challenge: {concept_name}"
                pedagogical_focus = "Demonstrate synthesis, rigorous edge-case transfer, and teach-back capability."
                steps = [
                    GeneratedSessionStep(
                        order=1,
                        step_type="APPLY",
                        title="Real-World Production Scenario",
                        instruction="Implement a production-grade async retry pipeline with exponential backoff.",
                        prompt="Provide the Dart stream transformer implementation handling socket timeouts.",
                        question_type="open_ended",
                        rubric_criteria="Correct backoff jitter, stream cancellation, and resource release."
                    ),
                    GeneratedSessionStep(
                        order=2,
                        step_type="TRANSFER",
                        title="Cross-Domain Transfer",
                        instruction="How would you adapt this mechanism to an offline-first distributed queue?",
                        prompt="Compare memory footprint vs durable storage guarantees.",
                        question_type="open_ended",
                        rubric_criteria="Understands durability trade-offs and backpressure."
                    ),
                    GeneratedSessionStep(
                        order=3,
                        step_type="TEACH",
                        title="Teach-Back Demonstration",
                        instruction="Explain this architecture to a junior engineer without using buzzwords.",
                        prompt="Summarize how reactive streams prevent UI stutter.",
                        question_type="open_ended",
                        rubric_criteria="Clear analogy, empathetic tone, technical precision."
                    ),
                ]
            else:
                sess_type = "PRACTICE"
                title = f"Guided Practice: {concept_name}"
                pedagogical_focus = "Strengthen active recall and procedural fluency."
                steps = [
                    GeneratedSessionStep(
                        order=1,
                        step_type="RECALL",
                        title="Active Concept Retrieval",
                        instruction="Retrieve the core invariants without looking at references.",
                        prompt=f"What are the 2 essential properties of {concept_name}?",
                        question_type="open_ended",
                        rubric_criteria="Correctly lists fundamental definitions and constraints."
                    ),
                    GeneratedSessionStep(
                        order=2,
                        step_type="PRACTICE",
                        title="Guided Problem Solving",
                        instruction="Solve this intermediate challenge step-by-step.",
                        prompt="Write code applying this concept to handle concurrent inputs.",
                        question_type="open_ended",
                        rubric_criteria="Correct implementation and error boundaries."
                    ),
                ]

            return GeneratedSessionPlan(
                session_title=title,
                session_type=sess_type,
                concept_id="concept_active",
                concept_name=concept_name,
                pedagogical_focus=pedagogical_focus,
                estimated_minutes=18,
                steps=steps,
            )  # type: ignore

        elif response_schema == EvaluationResult:
            # Deterministic pedagogical evaluation
            p_lower = prompt.lower()
            return EvaluationResult(
                score=86.0,
                reasoning_score=88.0,
                transfer_score=82.0,
                accuracy_score=86.0,
                completeness_score=85.0,
                feedback="Strong conceptual explanation. Clear grasp of core mechanisms and boundary conditions.",
                improvements=[
                    "Solidified invariant termination mechanics.",
                    "Correctly identified activation record unwinding.",
                ],
                focus_areas=[
                    "Continue practicing asynchronous stream backpressure handling.",
                ],
                misconceptions_detected=[],
                resolved_misconceptions=["base_case_termination"] if "base" in p_lower or "recurs" in p_lower else [],
                mastery_delta=7.5,
                confidence_delta=6.0,
                step_evaluations=[
                    StepEvaluation(
                        step_id="step_mock_1",
                        question="Core concept problem",
                        user_answer="Correct invariant guard",
                        is_correct=True,
                        correct_answer="Correct invariant guard",
                        explanation="Properly protects the recursion limit and prevents frame overflow.",
                    ),
                    StepEvaluation(
                        step_id="step_mock_2",
                        question="Call stack mechanism",
                        user_answer="LIFO unwinding",
                        is_correct=True,
                        correct_answer="LIFO unwinding",
                        explanation="Call stack unwinds in LIFO order upon reaching the base condition.",
                    ),
                ],
            )  # type: ignore

        elif response_schema == ExtractedConceptList:
            p_lower = prompt.lower()
            concepts = []
            if "stream" in p_lower or "dart" in p_lower or "async" in p_lower:
                concepts = [
                    ExtractedConcept(
                        name="Dart Async & Streams",
                        description="Asynchronous data sequences, event handling, and stream subscriptions.",
                        difficulty_level="intermediate",
                        prerequisites=["dart_basics"],
                        relevance_score=0.96,
                    ),
                    ExtractedConcept(
                        name="StreamController Architecture",
                        description="Managing sink ingestion, broadcast streams, and reactive listeners.",
                        difficulty_level="advanced",
                        prerequisites=["dart_async_and_streams"],
                        relevance_score=0.92,
                    ),
                ]
            elif "recurs" in p_lower:
                concepts = [
                    ExtractedConcept(
                        name="Recursion",
                        description="Decomposing problems into invariant self-similar sub-problems.",
                        difficulty_level="intermediate",
                        prerequisites=["functions", "stack_memory"],
                        relevance_score=0.95,
                    )
                ]
            else:
                concepts = [
                    ExtractedConcept(
                        name="Software Engineering Invariants",
                        description="Fundamental structural properties and state management constraints.",
                        difficulty_level="intermediate",
                        prerequisites=[],
                        relevance_score=0.90,
                    )
                ]

            return ExtractedConceptList(
                concepts=concepts,
                primary_domain="Software Engineering",
                summary="Extracted fundamental conceptual models and dependency structures.",
            )  # type: ignore

        elif response_schema == MentorDecisionAIOutput:
            return MentorDecisionAIOutput(
                reply="Let's build upon yesterday's session with targeted retrieval practice.",
                action_type="REVISE",
                action_title="Quick Retrieval Check: Event Loops",
                action_reason="Your retention risk on async streams has reached medium threshold (5 days since last practice).",
                estimated_minutes=4,
                concept_name="dart_async_and_streams",
            )  # type: ignore

        elif response_schema == MentorRecommendationOutput:
            intent = "LEARN"
            title = "Master Current Concept"
            reason = "Focus on core invariants to build stable mastery."
            concept_id = "concept_active"

            p_lower = prompt.lower()
            if "remediate" in p_lower:
                intent = "REMEDIATE"
                title = "Fix Foundational Prerequisite"
                reason = "A foundational prerequisite has low mastery (< 60%) or active misconceptions."
                concept_id = "concept_prerequisite"
            elif "revise" in p_lower:
                intent = "REVISE"
                title = "Quick Retrieval Review"
                reason = "Memory decay threshold reached for previously studied concepts."
                concept_id = "concept_retrieval"
            elif "prove" in p_lower:
                intent = "PROVE"
                title = "Verification Proof Challenge"
                reason = "High self-reported confidence without verified performance evidence."
                concept_id = "concept_proof"
            elif "practice" in p_lower:
                intent = "PRACTICE"
                title = "Targeted Problem Practice"
                reason = "Apply mental models to real-world edge cases."
                concept_id = "concept_practice"

            return MentorRecommendationOutput(
                intent=intent,
                concept_id=concept_id,
                title=title,
                reason=reason,
                estimated_minutes=15,
                confidence=0.94,
            )  # type: ignore

        elif response_schema == PersonalizedStudyNotesAIOutput:
            p_lower = prompt.lower()
            topic = "Target Concept"
            if "recurs" in p_lower:
                topic = "Recursion & Base Cases"
                weakness = "Allowing negative numbers (n <= 0) to bypass termination guards, causing stack overflow."
                remember = "Every recursive step must decrement towards a guarded invariant base case."
            elif "stream" in p_lower or "async" in p_lower:
                topic = "Dart Streams & Event Loops"
                weakness = "Forgetting to close StreamController sinks and potential multi-listener broadcast contention."
                remember = "Use broadcast streams for multiple subscribers and always cancel subscriptions in dispose."
            else:
                topic = "Core Software Architecture"
                weakness = "Overlooking edge-case boundary validations and state synchronization."
                remember = "Isolate invariants early and verify state transitions before applying mutations."

            return PersonalizedStudyNotesAIOutput(
                title=f"Personalized Study Notes: {topic}",
                summary=f"Synthesized mastery guide for {topic} tailored to your current cognitive evidence and known misconceptions.",
                key_points=[
                    f"Core invariant principles of {topic} must be maintained under concurrent execution.",
                    "Activation frames unwind predictably in LIFO order upon reaching termination criteria.",
                    "Separation of concerns between state mutation and event propagation prevents cascading faults.",
                ],
                your_weakness=weakness,
                remember_this=remember,
                next_action=f"Complete a 10-minute diagnostic challenge on {topic}.",
            )  # type: ignore

        elif response_schema == TeachEvaluationAIOutput:
            p_lower = prompt.lower()
            has_error = (
                "flaw" in p_lower
                or "infinite" in p_lower
                or "crash" in p_lower
                or "forgot" in p_lower
                or "wrong" in p_lower
                or "misconception" in p_lower
            )
            is_empty_or_short = len(prompt.strip()) < 80

            if is_empty_or_short:
                return TeachEvaluationAIOutput(
                    conceptual_accuracy=42,
                    completeness=35,
                    reasoning=40,
                    confidence=50,
                    transfer=30,
                    misconceptions=["superficial_explanation"],
                    missing_concepts=["core_definition", "mechanisms", "invariants"],
                    recommendation="LEARN",
                    feedback_summary="Explanation is too brief to demonstrate operational mental models.",
                    key_strengths=["Attempted initial articulation"],
                    growth_areas=["Elaborate with concrete mechanics, state transitions, and examples."],
                )  # type: ignore
            elif has_error:
                return TeachEvaluationAIOutput(
                    conceptual_accuracy=62,
                    completeness=68,
                    reasoning=59,
                    confidence=75,
                    transfer=55,
                    misconceptions=["base_case_termination_flaw"],
                    missing_concepts=["negative_bound_guards"],
                    recommendation="REMEDIATE",
                    feedback_summary="Identified sound high-level intuition, but exhibited a critical flaw in boundary termination semantics.",
                    key_strengths=["Clear high-level recursive intuition", "Confident articulation"],
                    growth_areas=["Resolve base case termination conditions on negative integer inputs."],
                )  # type: ignore
            else:
                return TeachEvaluationAIOutput(
                    conceptual_accuracy=88,
                    completeness=71,
                    reasoning=91,
                    confidence=82,
                    transfer=64,
                    misconceptions=[],
                    missing_concepts=["memory_consumption_invariants"],
                    recommendation="PRACTICE",
                    feedback_summary="Strong causal explanation demonstrating solid mental models of stack frames and termination invariants.",
                    key_strengths=["Rigorous explanation of stack frame unwinding", "Clear base case invariants"],
                    growth_areas=["Explore cross-domain transfer to tree traversal and memoization."],
                )  # type: ignore

        # Fallback dummy initialization for arbitrary Pydantic models
        try:
            return response_schema.model_validate({})
        except Exception:
            # Attempt default constructor
            return response_schema()

    async def embed(
        self,
        texts: List[str],
        **kwargs
    ) -> List[List[float]]:
        logger.debug(f"[MockLLM] embed requested for {len(texts)} text chunks")
        results: List[List[float]] = []
        dim = 1536
        for text in texts:
            # Generate deterministic pseudo-embedding based on hash
            hash_val = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            vec = [
                math.sin(hash_val + i * 0.05) / math.sqrt(dim)
                for i in range(dim)
            ]
            results.append(vec)
        return results

    async def evaluate(
        self,
        rubric: str,
        target_content: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        logger.debug(f"[MockLLM] evaluate against rubric with content length: {len(target_content)}")
        score = 85.0
        if not target_content or len(target_content.strip()) < 10:
            score = 40.0
            feedback = "Submission too brief to evaluate genuine understanding."
        else:
            feedback = "Demonstrates good mental model and clear application of core principles."

        return {
            "score": score,
            "accuracy": score,
            "reasoning": score + 2.0 if score < 95 else 98.0,
            "transfer": score - 3.0,
            "feedback": feedback,
            "misconceptions": [] if score >= 80 else ["partial_misunderstanding"],
        }
