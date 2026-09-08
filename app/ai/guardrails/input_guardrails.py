import re
from typing import Optional, Tuple
from dataclasses import dataclass
from app.core.logging import logger


@dataclass
class GuardrailResult:
    is_safe: bool
    sanitized_input: str
    rejection_reason: Optional[str] = None
    redirected_response: Optional[str] = None


class InputGuardrail:
    """
    Deterministic zero-cost guardrail protecting SkillTwin AI Mentor from:
    1. System prompt leakage and instruction override attacks.
    2. Secret, API key, and environment exfiltration attempts.
    3. Adversarial jailbreaks (DAN, Developer Mode, uncensored persona overrides).
    4. Malicious defamation and harmful generation attempts.

    Neutralizes attacks instantly before consuming any LLM tokens and redirects the learner
    productively to their current study topic.
    """

    # 1. Patterns attempting to extract or override system instructions
    INSTRUCTION_OVERRIDE_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior|above|former)\s+(instructions|prompts|rules|commands|constraints)",
        r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)",
        r"forget\s+(all\s+)?(previous|prior|system)\s+(instructions|rules|prompts)",
        r"(reveal|show|print|output|display|repeat|tell\s+me)\s+(your\s+)?(system\s+prompt|initial\s+instructions|system\s+message|hidden\s+rules|developer\s+prompt)",
        r"(what\s+are|what\'s)\s+(your\s+)?(system\s+instructions|system\s+prompt|initial\s+prompt|rules\s+given\s+to\s+you)",
        r"repeat\s+everything\s+(above|before\s+this)",
        r"print\s+everything\s+above",
        r"output\s+the\s+text\s+above",
    ]

    # 2. Patterns attempting to exfiltrate secret keys or operational credentials
    EXFILTRATION_PATTERNS = [
        r"(what\s+is|show|reveal|give\s+me|print)\s+(the\s+)?(api\s*key|secret\s*key|gemini\s*key|openai\s*key|access\s*token|jwt\s*secret|bearer\s*token)",
        r"(database|db|postgres|sqlite|supabase)\s*(password|connection\s*string|credentials|url)",
        r"(environment|env)\s*(variable|variables|vars|\.env)",
        r"backend\s*(secret|keys|config|credentials)",
    ]

    # 3. Patterns attempting jailbreaks or unrestricted persona overrides
    JAILBREAK_PATTERNS = [
        r"you\s+are\s+now\s+(dan|an\s+unrestricted|an\s+uncensored|evil|jailbroken)",
        r"do\s+anything\s+now",
        r"(developer|maintenance|root|admin|debug|super-user|god)\s+mode\s+(enabled|activated|on)",
        r"(pretend|act\s+as\s+if)\s+you\s+have\s+no\s+(rules|restrictions|ethics|guidelines|limits)",
        r"bypass\s+(all\s+)?(safety|content|ethical|system)\s+(filters|guidelines|rules|guardrails)",
        r"jailbreak",
    ]

    # 4. Patterns attempting brand defamation or malicious harm
    DEFAMATION_PATTERNS = [
        r"(say|tell\s+everyone|claim)\s+(that\s+)?skilltwin\s+is\s+(a\s+scam|trash|useless|terrible|bad|fake|stolen)",
        r"skilltwin\s+sucks",
    ]

    def __init__(self):
        self._compiled_override = [re.compile(p, re.IGNORECASE) for p in self.INSTRUCTION_OVERRIDE_PATTERNS]
        self._compiled_exfiltration = [re.compile(p, re.IGNORECASE) for p in self.EXFILTRATION_PATTERNS]
        self._compiled_jailbreak = [re.compile(p, re.IGNORECASE) for p in self.JAILBREAK_PATTERNS]
        self._compiled_defamation = [re.compile(p, re.IGNORECASE) for p in self.DEFAMATION_PATTERNS]

    def validate(
        self,
        user_message: str,
        active_goal_title: Optional[str] = None,
        current_topic_title: Optional[str] = None,
    ) -> GuardrailResult:
        """
        Validates and sanitizes a learner message.
        If a safety boundary or prompt injection attempt is detected, returns an authoritative,
        courteous pedagogical redirection without invoking the LLM.
        """
        clean_msg = user_message.strip()
        goal_ref = active_goal_title or "your current curriculum"
        topic_ref = current_topic_title or "today's scheduled milestone"

        # Check instruction override
        for pattern in self._compiled_override:
            if pattern.search(clean_msg):
                logger.warning(f"Guardrail triggered [INSTRUCTION_OVERRIDE]: '{clean_msg[:50]}...'")
                return GuardrailResult(
                    is_safe=False,
                    sanitized_input="",
                    rejection_reason="INSTRUCTION_OVERRIDE_DETECTED",
                    redirected_response=(
                        f"I am your SkillTwin AI Mentor, dedicated exclusively to guiding you toward mastery of "
                        f"**{goal_ref}**.\n\n"
                        f"I operate strictly under pedagogical guidelines and cannot reveal or modify internal instructions. "
                        f"Let's channel our cognitive energy into what matters: **{topic_ref}**.\n\n"
                        f"What concept or problem would you like to master today?"
                    ),
                )

        # Check credential exfiltration
        for pattern in self._compiled_exfiltration:
            if pattern.search(clean_msg):
                logger.warning(f"Guardrail triggered [EXFILTRATION]: '{clean_msg[:50]}...'")
                return GuardrailResult(
                    is_safe=False,
                    sanitized_input="",
                    rejection_reason="EXFILTRATION_DETECTED",
                    redirected_response=(
                        f"I cannot disclose API keys, backend secrets, or environment credentials. "
                        f"My purpose is to guide your deliberate practice and retention in **{goal_ref}**.\n\n"
                        f"Let's refocus on your current topic: **{topic_ref}**."
                    ),
                )

        # Check jailbreaks
        for pattern in self._compiled_jailbreak:
            if pattern.search(clean_msg):
                logger.warning(f"Guardrail triggered [JAILBREAK]: '{clean_msg[:50]}...'")
                return GuardrailResult(
                    is_safe=False,
                    sanitized_input="",
                    rejection_reason="JAILBREAK_DETECTED",
                    redirected_response=(
                        f"I cannot adopt unrestricted or external personas. I am your SkillTwin Mentor, "
                        f"focused on deliberate practice, cognitive evidence, and your success in **{goal_ref}**.\n\n"
                        f"Shall we continue with **{topic_ref}**?"
                    ),
                )

        # Check defamation / malicious prompting
        for pattern in self._compiled_defamation:
            if pattern.search(clean_msg):
                logger.warning(f"Guardrail triggered [DEFAMATION]: '{clean_msg[:50]}...'")
                return GuardrailResult(
                    is_safe=False,
                    sanitized_input="",
                    rejection_reason="MALICIOUS_PROMPTING",
                    redirected_response=(
                        f"SkillTwin is built to accelerate your learning through evidence-backed cognitive science. "
                        f"I'm here to support your growth in **{goal_ref}**. Let's tackle **{topic_ref}** together."
                    ),
                )

        # Sanitize input: strip control characters, escape potential tag delimiters
        sanitized = clean_msg.replace("<LEARNER_CONTEXT>", "").replace("</LEARNER_CONTEXT>", "")
        sanitized = sanitized.replace("<USER_QUERY>", "").replace("</USER_QUERY>", "")
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)

        return GuardrailResult(is_safe=True, sanitized_input=sanitized)


# Singleton instance
input_guardrail = InputGuardrail()
