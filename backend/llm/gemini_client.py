# Role: Minimal wrapper around Gemini API. Centralizes model name, temperature, and error handling,
# so the rest of the code calls a single method: generate_text(prompt).

import os
from typing import Optional

from google import genai


class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> None:
        # Key lines:
        # - Reads secrets from env (no secrets in code).
        # - Model and temperature are configurable for experiments.
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing GEMINI_API_KEY in environment or .env")

        self.model_name = model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        self.temperature = temperature

        self.client = genai.Client(api_key=self.api_key)

    def generate_text(self, prompt: str) -> str:
        # 1) Validate prompt
        # 2) Call Gemini (single text completion)
        # 3) Validate non-empty response
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must be non-empty.")

        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={"temperature": self.temperature},
            )
        except Exception as e:
            raise RuntimeError(f"Gemini API call failed: {e}") from e

        text = getattr(resp, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")

        return text.strip()
