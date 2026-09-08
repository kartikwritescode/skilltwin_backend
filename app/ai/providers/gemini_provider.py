import json
import re
from typing import TypeVar, Type, Optional, List, Dict, Any
import httpx
from pydantic import BaseModel

from app.ai.providers.base import LLMProvider
from app.ai.providers.mock_provider import MockLLMProvider
from app.core.logging import logger

T = TypeVar("T", bound=BaseModel)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiLLMProvider(LLMProvider):
    """
    Production-grade Google Gemini AI provider calling Gemini REST API directly.
    Supports chat, structured JSON schemas, embeddings, and evaluation.
    Falls back gracefully to MockLLMProvider if network or API limits are hit.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.1-flash-lite",
        fallback: Optional[LLMProvider] = None,
    ):
        self.api_key = api_key
        # Clean model name (e.g. ensure 'gemini-3.1-flash-lite' format)
        self.model = model.replace("models/", "") if model else "gemini-3.1-flash-lite"
        self._fallback = fallback or MockLLMProvider()
        self.last_status: str = "active"
        self.last_error_detail: Optional[str] = None
        self._is_placeholder = (
            not self.api_key
            or "placeholder" in self.api_key.lower()
            or self.api_key == "mock-key"
        )
        if self._is_placeholder:
            self.last_status = "placeholder_key"
            logger.warning("GeminiLLMProvider initialized with placeholder key; using Mock fallback.")

    @property
    def provider_name(self) -> str:
        return f"gemini ({self.model})"

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> str:
        if self._is_placeholder:
            return await self._fallback.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        url = f"{GEMINI_BASE_URL}/models/{self.model}:generateContent?key={self.api_key}"
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}],
            }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "").strip()
                            if text:
                                self.last_status = "active"
                                self.last_error_detail = None
                                return text
                elif res.status_code == 429:
                    self.last_status = "quota_exhausted"
                    self.last_error_detail = "Google Gemini Free Tier quota exceeded (HTTP 429). Offline pedagogical intelligence active."
                    logger.warning(f"Gemini API quota exhausted (429): {res.text[:150]}")
                elif res.status_code == 404:
                    self.last_status = "model_not_found"
                    self.last_error_detail = f"Gemini model '{self.model}' not found or deprecated for this API key (HTTP 404)."
                    logger.warning(f"Gemini model 404: {res.text[:150]}")
                else:
                    self.last_status = f"http_{res.status_code}"
                    self.last_error_detail = f"Gemini API error {res.status_code}: {res.text[:100]}"
                    logger.warning(
                        f"Gemini generate_text API returned {res.status_code}: {res.text[:150]}, using fallback."
                    )
        except Exception as e:
            self.last_status = "connection_error"
            self.last_error_detail = f"Gemini connection error: {str(e)[:100]}"
            logger.error(f"Gemini API error during generate_text: {e}, falling back to mock provider.")

        return await self._fallback.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        **kwargs,
    ) -> T:
        if self._is_placeholder:
            return await self._fallback.generate_structured(
                prompt=prompt,
                response_schema=response_schema,
                system_prompt=system_prompt,
                temperature=temperature,
                **kwargs,
            )

        url = f"{GEMINI_BASE_URL}/models/{self.model}:generateContent?key={self.api_key}"
        
        # Include json schema instructions
        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        augmented_prompt = f"""
{prompt}

CRITICAL: Return ONLY a valid JSON object strictly matching this schema:
{schema_json}
""".strip()

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": augmented_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "response_mime_type": "application/json",
            },
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}],
            }

        candidate_models = [self.model]
        if "gemini-3.1-flash-lite" not in candidate_models:
            candidate_models.append("gemini-3.1-flash-lite")
        if "gemini-flash-latest" not in candidate_models:
            candidate_models.append("gemini-flash-latest")

        for try_model in candidate_models:
            url = f"{GEMINI_BASE_URL}/models/{try_model}:generateContent?key={self.api_key}"
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                raw_json = parts[0].get("text", "").strip()
                                # Strip markdown backticks if present
                                clean_json = re.sub(r"^```json\s*", "", raw_json, flags=re.IGNORECASE)
                                clean_json = re.sub(r"```$", "", clean_json.strip())
                                self.last_status = "active"
                                self.last_error_detail = None
                                return response_schema.model_validate_json(clean_json)
                    elif res.status_code == 429:
                        self.last_status = "quota_exhausted"
                        self.last_error_detail = "Google Gemini Free Tier quota exceeded (HTTP 429). Offline pedagogical intelligence active."
                        logger.warning(f"Gemini API quota exhausted (429) on {try_model}: {res.text[:150]}")
                        break
                    elif res.status_code in [404, 503]:
                        logger.warning(f"Gemini model '{try_model}' returned {res.status_code}, trying alternate model if available...")
                        continue
                    else:
                        self.last_status = f"http_{res.status_code}"
                        self.last_error_detail = f"Gemini API error {res.status_code}: {res.text[:100]}"
                        logger.warning(
                            f"Gemini generate_structured returned {res.status_code} on {try_model}: {res.text[:150]}"
                        )
            except Exception as e:
                logger.warning(f"Gemini API error on {try_model}: {e}")

        return await self._fallback.generate_structured(
            prompt=prompt,
            response_schema=response_schema,
            system_prompt=system_prompt,
            temperature=temperature,
            **kwargs,
        )

    async def embed(
        self,
        texts: List[str],
        **kwargs,
    ) -> List[List[float]]:
        if self._is_placeholder or not texts:
            return await self._fallback.embed(texts, **kwargs)

        embed_model = kwargs.get("model", "text-embedding-004").replace("models/", "")
        url = f"{GEMINI_BASE_URL}/models/{embed_model}:batchEmbedContents?key={self.api_key}"

        requests_payload = [
            {
                "model": f"models/{embed_model}",
                "content": {"parts": [{"text": text}]},
            }
            for text in texts
        ]

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(url, json={"requests": requests_payload})
                if res.status_code == 200:
                    embeddings = res.json().get("embeddings", [])
                    if embeddings:
                        return [e.get("values", []) for e in embeddings]
        except Exception as e:
            logger.error(f"Gemini embedding error: {e}, using fallback embeddings.")

        return await self._fallback.embed(texts, **kwargs)

    async def evaluate(
        self,
        rubric: str,
        target_content: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        prompt = f"""
RUBRIC:
{rubric}

TARGET LEARNER CONTENT:
{target_content}

CONTEXT:
{json.dumps(context or {})}

Evaluate the target content against the rubric.
Return a JSON object with:
- score: float (0.0 to 1.0)
- is_passing: bool
- feedback: string
- key_gaps: list of strings
- strength_areas: list of strings
""".strip()

        if self._is_placeholder:
            return await self._fallback.evaluate(
                rubric=rubric,
                target_content=target_content,
                context=context,
                **kwargs,
            )

        try:
            url = f"{GEMINI_BASE_URL}/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                },
            }
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    parts = data["candidates"][0]["content"]["parts"]
                    text = parts[0]["text"]
                    return json.loads(text)
        except Exception as e:
            logger.error(f"Gemini evaluation error: {e}, falling back to mock.")

        return await self._fallback.evaluate(
            rubric=rubric,
            target_content=target_content,
            context=context,
            **kwargs,
        )
