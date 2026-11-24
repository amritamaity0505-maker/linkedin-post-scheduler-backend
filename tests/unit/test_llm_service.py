import pytest
import requests

from backend.services.llm_service import LLMService, LLMServiceError


def test_generate_post_success(monkeypatch):
    svc = LLMService()

    mock_generated_text = (
        "Here's the truth about scalable distributed workers:\n\n"
        "Row-level locking with SKIP LOCKED is 10x simpler than running Celery with Redis for modest workloads.\n\n"
        "What's your preferred approach to background jobs?\n\n"
        "#Python #SoftwareEngineering #Architecture"
    )

    class MockResponse:
        ok = True
        status_code = 200

        def json(self):
            return {"response": f"```markdown\n{mock_generated_text}\n```"}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: MockResponse())

    result = svc.generate_post(
        topic="Postgres and MySQL row locking vs Redis",
        tone="thought-leadership",
        audience="Senior Developers",
    )

    assert result["draft"] == mock_generated_text
    assert result["character_count"] == len(mock_generated_text)
    assert result["brief"]["topic"] == "Postgres and MySQL row locking vs Redis"


def test_generate_post_gemini_candidate_format(monkeypatch):
    svc = LLMService()

    mock_text = "Exciting milestone! We just completed our migration to high-concurrency architecture.\n\n• 0 downtime\n• 100% data integrity\n\n#Architecture #Engineering"

    class MockGeminiResponse:
        ok = True
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": mock_text}
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: MockGeminiResponse())

    result = svc.generate_post(topic="Architecture migration", tone="professional")
    assert result["draft"] == mock_text
    assert result["character_count"] == len(mock_text)


def test_sanitize_output_strips_intros():
    svc = LLMService()
    raw = "Here is your LinkedIn post:\n\nStop over-engineering distributed tasks.\n\n#Tech"
    sanitized = svc._sanitize_output(raw)
    assert sanitized == "Stop over-engineering distributed tasks.\n\n#Tech"


def test_sanitize_output_strips_asterisks_and_markdown():
    svc = LLMService()
    raw = (
        "### Scaling MySQL with Zero Downtime\n\n"
        "**Scaling MySQL with zero downtime is no easy feat.**\n\n"
        "* **Plan for Sharding Early**: Don't wait until database crashes.\n"
        "- **Read Replicas**: Implement read replicas to offload read traffic.\n\n"
        "**What strategies have you implemented? Let's discuss below.** 🚀\n\n"
        "#SystemDesign #MySQL #Backend"
    )
    sanitized = svc._sanitize_output(raw)
    # Check no asterisks or stray hashes remain
    assert "**" not in sanitized
    assert "*" not in sanitized
    assert "###" not in sanitized
    assert "• Plan for Sharding Early: Don't wait until database crashes." in sanitized
    assert "• Read Replicas: Implement read replicas to offload read traffic." in sanitized
    assert "#SystemDesign #MySQL #Backend" in sanitized


def test_enforce_maximum_3000_chars():
    svc = LLMService()
    long_text = "Word " * 700  # 3500 chars
    sanitized = svc._sanitize_output(long_text)
    assert len(sanitized) <= 3000


def test_llm_timeout_raises_llm_service_error(monkeypatch):
    svc = LLMService()

    def mock_timeout(*args, **kwargs):
        raise requests.Timeout("Model inference timeout")

    monkeypatch.setattr(requests, "post", mock_timeout)

    with pytest.raises(LLMServiceError) as exc_info:
        svc.generate_post(topic="Timeout test")

    assert exc_info.value.status_code == 504
