"""Gemini text generation provider (TechStack §6: Gemini 2.5 Pro, temp 0.2).

Injected via DI so tests substitute a deterministic fake — the LangGraph
orchestration is therefore testable without an API key or network. The real
provider is only instantiated when GEMINI_API_KEY is set.
"""

from typing import Protocol

import structlog

log = structlog.get_logger("app.ai.agents.gemini")


class LLMProvider(Protocol):
    async def generate(self, *, system: str, prompt: str) -> str: ...


class GeminiProvider:
    """Lazy client for Gemini 2.5 Pro (google-generativeai)."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-pro", temperature: float = 0.2):
        self._api_key = api_key
        self._model_name = model
        self._temperature = temperature
        self._model = None

    def _ensure(self):
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(self._model_name)
            log.info("gemini_initialised", model=self._model_name)
        return self._model

    async def generate(self, *, system: str, prompt: str) -> str:
        import anyio
        import google.generativeai as genai

        model = self._ensure()

        def _call() -> str:
            resp = model.generate_content(
                f"{system}\n\n{prompt}",
                generation_config=genai.types.GenerationConfig(
                    temperature=self._temperature, response_mime_type="application/json"
                ),
            )
            return resp.text

        return await anyio.to_thread.run_sync(_call)
