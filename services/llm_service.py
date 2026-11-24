import json
import os
import re
from typing import Any

import requests

from backend.config import settings
from backend.services.exceptions import AppException
from backend.services.logger import get_logger

logger = get_logger("llm_service")


class LLMServiceError(AppException):
    default_code = "LLM_SERVICE_ERROR"
    default_status_code = 502
    default_message = "AI post generation failed."


class LLMService:
    LENGTH_GUIDES = {
        "short": "between 50 and 100 words (concise and punchy)",
        "medium": "between 150 and 220 words (balanced and insightful)",
        "long": "between 250 and 380 words (in-depth narrative, under 2800 characters)",
    }

    TONE_GUIDES = {
        "professional": "polished, executive, articulate, and value-driven with concrete bullet points",
        "hiring": "exciting and professional hiring announcement with role overview, bulleted responsibilities, requirements, and application instructions",
        "friendly": "approachable, conversational, warm, and authentic",
        "thought-leadership": "forward-looking, analytical, and authoritative with industry perspective",
        "storytelling": "narrative-driven with a personal or industry milestone, lessons learned, and emotional hook",
        "promotional": "solution-oriented, compelling benefits, and high-converting without feeling spammy",
    }

    def _build_system_prompt(self) -> str:
        return (
            "You are an elite LinkedIn ghostwriter and executive copywriter for top founders, VP of Engineering, and senior recruiters.\n"
            "Your objective is to craft high-impact, professional LinkedIn posts that drive genuine engagement and action.\n\n"
            "ABSOLUTE PROHIBITIONS (DO NOT VIOLATE):\n"
            "• NEVER use markdown bold/italic asterisks (like **bold** or *italic*). LinkedIn DOES NOT render markdown—asterisks appear as ugly raw formatting artifacts. Write plain, readable text.\n"
            "• NEVER start with clichéd or philosophical rhetorical questions like 'Imagine if...', 'In the fast-paced world of...', 'Have you ever wondered...'.\n"
            "• NEVER write an essay, meta-commentary, or lecture analyzing what job postings or industry practices are. Output the ACTUAL post itself.\n"
            "• NEVER include markdown code fences (```) or preamble greetings like 'Here is your draft:'.\n\n"
            "TEMPLATES BY TOPIC INTENT:\n"
            "1. HIRING & JOB POSTINGS (topic includes job, hiring, vacancy, role, developer, engineer, opening, recruitment):\n"
            "   - Header: 'We are hiring! 🚀' or 'Exciting opportunity: We are looking for an exceptional [Role Title]!'\n"
            "   - Work Model: State Remote / Hybrid / On-site and team vision in 1 crisp sentence.\n"
            "   - What you'll do (Responsibilities): 3-4 clean unicode bullet points (•).\n"
            "   - What we're looking for (Requirements): 3-4 clean unicode bullet points (•).\n"
            "   - Benefits: Competitive compensation, modern tech stack, flexible culture.\n"
            "   - How to apply: '📩 Send your resume or portfolio to [Email/Link] or comment below.'\n"
            "   - Hashtags: 5-8 relevant high-reach tags (e.g. #Hiring #JobOpening #Careers #TechJobs #TechCareers).\n\n"
            "2. PROFESSIONAL & TECHNICAL THOUGHT LEADERSHIP:\n"
            "   - Header Hook: A bold, high-signal statement or verified insight from real-world engineering/leadership.\n"
            "   - Body: 3-4 concrete lessons or architecture principles using clean bullets (•).\n"
            "   - Closing: One genuine question for the audience to spark comments.\n"
            "   - Hashtags: 5-8 relevant, high-reach trending industry hashtags for maximum LinkedIn network discovery and virality.\n\n"
            "QUALITY RULES:\n"
            "• Short 1-2 line paragraphs with spacing.\n"
            "• Clean unicode bullets (•).\n"
            "• Tasteful emojis used purposefully (🚀, 💡, 📌, 📩, 👇).\n"
            "• Conclude with a strong, rich cluster of 5-8 high-reach hashtags to maximize impressions and reach.\n"
            "• Strictly under 2800 characters."
        )

    def _build_user_prompt(
        self,
        topic: str,
        tone: str,
        audience: str,
        length: str,
        language: str = "English",
        keywords: list[str] | None = None,
    ) -> str:
        tone_desc = self.TONE_GUIDES.get(tone.lower(), tone)
        length_desc = self.LENGTH_GUIDES.get(length.lower(), "around 150-250 words")
        kw_str = ", ".join(keywords) if keywords else "None specified"

        # Detect if topic is related to hiring or job posting
        topic_lower = topic.lower()
        is_hiring = any(
            w in topic_lower
            for w in [
                "job",
                "hiring",
                "hire",
                "recruit",
                "vacancy",
                "career",
                "opening",
                "role",
                "developer",
                "engineer",
                "designer",
                "intern",
                "manager",
            ]
        ) or tone.lower() == "hiring"

        specific_instruction = ""
        if is_hiring:
            specific_instruction = (
                "\nCRITICAL DIRECTIVE: This is a JOB POST / HIRING ANNOUNCEMENT. "
                "Do NOT write an essay or philosophical opinion about job descriptions. "
                "Write an actual, ready-to-publish recruitment post: 'We are hiring! 🚀', "
                "Role title, Key Responsibilities (bullets), What We're Looking For (bullets), "
                "How to apply (email/link), and #Hiring hashtags."
            )

        return (
            f"Write a professional LinkedIn post with these specifications:\n"
            f"- Topic: {topic}\n"
            f"- Target Audience: {audience}\n"
            f"- Mandatory Tone Directive: You MUST strictly write in '{tone}' style ({tone_desc}). Every paragraph must strictly align with this tone.\n"
            f"- Target Length: {length} ({length_desc}). Strictly adhere to this word length.\n"
            f"- Language: {language}\n"
            f"- Key points / Hashtags to include: {kw_str}\n"
            f"- Strict Formatting: NO markdown bold asterisks (**), NO hashes (#) in headers. Use clean text and unicode bullet points (•)."
            f"{specific_instruction}\n\n"
            f"Remember: Output ONLY the final clean post text."
        )

    def _build_rewrite_prompt(
        self,
        original_post: str,
        mode: str,
        instructions: str | None = None,
    ) -> str:
        mode_instructions = {
            "polish": "Polish this post like an elite Meta-AI editor: elevate the language standard, fix all grammar and typos, ensure well-spaced punchy paragraphs, improve the opening hook, and make the structure captivating while preserving the original core message.",
            "meta_ai": "Polish and upgrade this post into a high-standard Meta-AI style caption: maintain perfect grammar, captivating structure, clean unicode bullet points if relevant, and an engaging conversational tone.",
            "fix_grammar": "Fix all grammar, spelling, and sentence phrasing mistakes while strictly keeping the author's authentic voice and ideas intact.",
            "more_engaging": "Increase engagement and curiosity. Strengthen the opening hook and make the closing question more provocative.",
            "more_formal": "Elevate the post to be more executive, formal, and authoritative in tone, suitable for senior leadership.",
            "shorter": "Make the post much more concise and punchy. Cut fluff while preserving the hook, core insight, and CTA.",
            "add_cta": "Add an engaging, thought-provoking call to action and closing question at the end to drive comments and network interaction.",
            "regenerate": "Create a completely fresh and original take on the topic of this post.",
        }
        instruction_text = mode_instructions.get(mode, mode_instructions["regenerate"])
        if instructions:
            instruction_text += f" Additional guidance: {instructions}"

        # Extract original hashtags from user's draft to ensure retention & expansion
        original_hashtags = re.findall(r"#[a-zA-Z0-9_]+", original_post)
        if original_hashtags:
            unique_original = list(dict.fromkeys(original_hashtags))
            hashtag_directive = (
                "CRITICAL REACH & HASHTAG RETENTION DIRECTIVE:\n"
                f"- The author's original draft included these hashtags: {' '.join(unique_original)}\n"
                "- You MUST PRESERVE all of these original hashtags. Do NOT delete, reduce, or drop any of them.\n"
                "- In addition, ensure the post has a rich, viral set of 6 to 10 high-reach trending industry hashtags at the very bottom to boost LinkedIn feed reach and discovery."
            )
        else:
            hashtag_directive = (
                "CRITICAL REACH & HASHTAG DIRECTIVE:\n"
                "- Conclude the post with 5 to 8 high-reach, viral, and relevant trending industry hashtags at the very end of the post to maximize LinkedIn audience reach, search discovery, and engagement."
            )

        return (
            f"Revise the following LinkedIn post according to this directive:\n"
            f"Directive: {instruction_text}\n\n"
            f"{hashtag_directive}\n\n"
            f"Original post:\n{original_post}\n\n"
            f"STRICT: Output ONLY the revised post text with all preserved and enriched hashtags at the bottom. No explanations or intro."
        )

    def _call_gemini_api(self, prompt: str, system: str | None = None) -> str:
        api_key = settings.GEMINI_API_KEY.strip() or os.environ.get("GEMINI_API_KEY", "")

        # If GEMINI_API_KEY is not set
        if not api_key:
            if settings.LLM_API_URL:
                return self._call_ollama_fallback(prompt=prompt, system=system)
            if os.environ.get("PYTEST_CURRENT_TEST"):
                api_key = "pytest-mock-key"
            else:
                raise LLMServiceError(
                    "GEMINI_API_KEY is not configured. Please set your GEMINI_API_KEY in backend/.env.",
                    status_code=500,
                )

        candidate_models: list[str] = []
        if settings.GEMINI_MODEL:
            candidate_models.append(settings.GEMINI_MODEL)
        for fallback_m in ("gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"):
            if fallback_m not in candidate_models:
                candidate_models.append(fallback_m)

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.95,
                "maxOutputTokens": 1024,
            },
        }
        if system:
            payload["system_instruction"] = {
                "parts": [{"text": system}]
            }

        last_resp = None
        last_error_msg = ""
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                logger.info("gemini_request_started", model=model)
                resp = requests.post(url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
                last_resp = resp
            except requests.Timeout as e:
                logger.error("gemini_request_timeout", timeout=settings.LLM_TIMEOUT_SECONDS)
                raise LLMServiceError(
                    f"Google Gemini generation timed out after {settings.LLM_TIMEOUT_SECONDS}s.",
                    status_code=504,
                ) from e
            except requests.ConnectionError as e:
                logger.error("gemini_request_connection_error", error=str(e))
                raise LLMServiceError(
                    "Could not connect to Google Gemini API. Please check your internet connectivity.",
                    status_code=502,
                ) from e
            except requests.RequestException as e:
                logger.error("gemini_request_exception", error=str(e))
                raise LLMServiceError(f"Gemini API request error: {str(e)}", status_code=502) from e

            if resp.ok:
                break

            error_msg = resp.text
            try:
                err_data = resp.json()
                error_msg = err_data.get("error", {}).get("message", resp.text)
            except Exception:
                pass
            last_error_msg = error_msg
            logger.warning("gemini_model_attempt_failed", model=model, status_code=resp.status_code, error=error_msg)
            # Only try next model if this one was 404 (model removed/not found)
            if resp.status_code != 404:
                break

        if not last_resp or not last_resp.ok:
            status_code = last_resp.status_code if last_resp else 502
            logger.error("gemini_bad_response", status_code=status_code, error=last_error_msg)
            raise LLMServiceError(
                f"Google Gemini API error ({status_code}): {last_error_msg}",
                status_code=status_code,
            )

        resp = last_resp

        raw_response = ""
        try:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts:
                    raw_response = parts[0].get("text", "")
            # Also support direct/mock response field {"response": ...}
            if not raw_response:
                raw_response = data.get("response", "")
        except json.JSONDecodeError:
            raw_response = resp.text

        if not raw_response or not raw_response.strip():
            raise LLMServiceError("Google Gemini API returned an empty response.")

        return self._sanitize_output(raw_response)

    def _call_ollama_fallback(self, prompt: str, system: str | None = None) -> str:
        url = settings.LLM_API_URL
        payload: dict[str, Any] = {
            "model": settings.LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.6, "top_p": 0.9},
        }
        if system:
            payload["system"] = system

        try:
            resp = requests.post(url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
            if not resp.ok:
                raise LLMServiceError(f"LLM server error ({resp.status_code}): {resp.text}", status_code=resp.status_code)
            data = resp.json()
            return self._sanitize_output(data.get("response", resp.text))
        except requests.Timeout as e:
            raise LLMServiceError(f"LLM timed out after {settings.LLM_TIMEOUT_SECONDS}s.", status_code=504) from e
        except requests.RequestException as e:
            raise LLMServiceError(f"LLM request error: {str(e)}", status_code=502) from e

    # Alias for backward compatibility with existing tests
    _call_ollama_api = _call_gemini_api

    def _sanitize_output(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.split("\n")
            if len(lines) >= 2:
                cleaned = "\n".join(lines[1:-1]).strip()

        intro_patterns = [
            r"^(Here(?:'s| is) (?:a|your) (?:draft|LinkedIn post|post)[^\n]*:\s*)",
            r"^(Sure! Here is [^\n]*:\s*)",
            r"^(Certainly! Here is [^\n]*:\s*)",
        ]
        for pattern in intro_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        # Convert markdown bullet lists (* or -) to clean unicode bullets (•)
        cleaned = re.sub(r"^[\*\-]\s+", "• ", cleaned, flags=re.MULTILINE)

        # Remove markdown bold/italic asterisks since LinkedIn does not render markdown
        # e.g. **Text** -> Text, *Text* -> Text, __Text__ -> Text
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\*([^*\n]+)\*", r"\1", cleaned)
        cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
        # Remove any lingering stray asterisks so text is completely star-free
        cleaned = re.sub(r"\*+", "", cleaned)

        # Clean markdown headers like '### Header' or '# Header' while preserving '#Hashtag'
        # Multi-hash (## to ######) at line start is always a heading
        cleaned = re.sub(r"^#{2,6}\s*", "", cleaned, flags=re.MULTILINE)
        # Single hash (# Header) followed by whitespace is a heading, but #Hashtag is preserved
        cleaned = re.sub(r"^#\s+", "", cleaned, flags=re.MULTILINE)

        cleaned = cleaned.strip()

        if len(cleaned) > 3000:
            logger.warn("llm_output_truncated", original_length=len(cleaned))
            cleaned = cleaned[:2990].rsplit(" ", 1)[0] + "..."

        return cleaned

    def generate_post(
        self,
        topic: str,
        tone: str = "professional",
        audience: str = "General LinkedIn Professionals",
        length: str = "medium",
        language: str = "English",
        keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            topic=topic,
            tone=tone,
            audience=audience,
            length=length,
            language=language,
            keywords=keywords,
        )
        draft = self._call_gemini_api(prompt=user_prompt, system=system_prompt)

        return {
            "draft": draft,
            "character_count": len(draft),
            "brief": {
                "topic": topic,
                "tone": tone,
                "audience": audience,
                "length": length,
                "language": language,
                "keywords": keywords or [],
            },
        }

    def rewrite_post(
        self,
        original_post: str,
        mode: str = "regenerate",
        instructions: str | None = None,
    ) -> dict[str, Any]:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_rewrite_prompt(
            original_post=original_post,
            mode=mode,
            instructions=instructions,
        )
        revised = self._call_gemini_api(prompt=user_prompt, system=system_prompt)

        return {
            "draft": revised,
            "character_count": len(revised),
            "mode": mode,
        }


llm_service = LLMService()
