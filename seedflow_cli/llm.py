from __future__ import annotations

import json
import os
import random
import string
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .security import DEFAULT_OPENROUTER_BASE_URL, SecurityOptions, validate_openrouter_base_url


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    @abstractmethod
    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        raise NotImplementedError

    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        text = self.chat_text(messages, model=model)

        for clean in _json_payload_candidates(text):
            try:
                return _loads_json(clean)
            except json.JSONDecodeError:
                continue

        raise LLMError(f"Model returned invalid seeded JSON: {text[:500]}")


class MockLLMClient(LLMClient):
    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        return self.chat_json(messages, model=model)

    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        prompt = messages[-1]["content"]
        seed = self._seed()

        if '"selected_index"' in prompt and '"candidates"' in prompt:
            return {
                "selected_index": 0,
                "score": 72,
                "reason": "Mock judge picks the first available candidate. Set OPENROUTER_API_KEY to use real judging.",
            }

        if '"payload_type": "angle"' in prompt:
            return {
                "candidate": {
                    "seed": {
                        "random_string": seed,
                        "interpretation": "Mock seed guided angle, hook and tone.",
                    },
                    "title": "Mock angle",
                    "summary": "Sharp mock article angle.",
                    "payload_type": "angle",
                    "payload": {
                        "thesis": "The article should argue from a concrete, opinionated angle instead of explaining the topic generically.",
                        "hook": "Start by challenging the reader's default assumption.",
                        "reader_promise": "The reader gets a usable mental model, not another AI thinkpiece.",
                        "tone": "Sharp, practical, non-corporate.",
                        "avoid": ["AI cliches", "generic transformation language"],
                    },
                }
            }

        if '"payload_type": "draft"' in prompt:
            return {
                "candidate": {
                    "seed": {
                        "random_string": seed,
                        "interpretation": "Mock seed guided draft hook, pacing and examples.",
                    },
                    "title": "Mock draft",
                    "summary": "Complete mock draft candidate.",
                    "payload_type": "draft",
                    "payload": {
                        "markdown": "# Mock draft\n\nThis is a mock article draft generated from accepted workflow context. Set OPENROUTER_API_KEY to use a real model.",
                    },
                }
            }

        if '"payload_type": "output"' in prompt:
            return {
                "candidate": {
                    "seed": {
                        "random_string": seed,
                        "interpretation": "Mock seed guided hook, order and specificity.",
                    },
                    "title": "Mock output",
                    "summary": "Complete mock output.",
                    "payload_type": "output",
                    "payload": {
                        "markdown": "# Mock output\n\nThis is a mock final output. Set OPENROUTER_API_KEY to use a real model.",
                    },
                }
            }

        return {
            "candidate": {
                "seed": {
                    "random_string": seed,
                    "interpretation": "Mock seed guided structure, tone and section order.",
                },
                "title": "Mock plan",
                "summary": "A simple mock plan candidate.",
                "payload_type": "plan",
                "payload": {
                    "items": [
                        {
                            "title": "Hook",
                            "purpose": "Start with a sharp opening tied to the selected angle.",
                            "key_points": ["State the tension", "Promise a concrete mechanism"],
                        },
                        {
                            "title": "Mechanism",
                            "purpose": "Explain the core idea concretely.",
                            "key_points": ["Show how the workflow makes decisions", "Avoid generic AI language"],
                        },
                        {
                            "title": "Payoff",
                            "purpose": "Show why the reader should care.",
                            "key_points": ["Connect to real output quality", "End with a clear takeaway"],
                        },
                    ]
                },
            }
        }

    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        prompt = messages[-1]["content"]
        marker = "Raw glued output:\n"

        if marker in prompt:
            return prompt.split(marker, 1)[1].strip()

        return "Mock text response. Set OPENROUTER_API_KEY to use a real model."

    def _seed(self) -> str:
        alphabet = string.ascii_letters + string.digits + "-_"
        value = "".join(random.choice(alphabet) for _ in range(48))
        return f"<random_string>{value}</random_string>"


class OpenRouterClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
        backoff_seconds: float | None = None,
    ) -> None:
        _ensure_ssl_cert_file()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = _env_int("OPENROUTER_MAX_RETRIES", 3) if max_retries is None else max(0, max_retries)
        self.timeout_seconds = max(1.0, _env_float("OPENROUTER_TIMEOUT_SECONDS", 120.0)) if timeout_seconds is None else max(1.0, timeout_seconds)
        self.backoff_seconds = _env_float("OPENROUTER_BACKOFF_SECONDS", 1.0) if backoff_seconds is None else max(0.0, backoff_seconds)

    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        text = self._chat(messages, model=model, json_mode=True)

        for clean in _json_payload_candidates(text):
            try:
                return _loads_json(clean)
            except json.JSONDecodeError:
                continue

        raise LLMError(f"Model returned invalid JSON: {text[:500]}")

    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        text = self._chat(messages, model=model, json_mode=False)

        for clean in _json_payload_candidates(text):
            try:
                return _loads_json(clean)
            except json.JSONDecodeError:
                continue

        raise LLMError(f"Model returned invalid seeded JSON: {text[:500]}")

    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        return self._chat(messages, model=model, json_mode=False)

    def _chat(self, messages: list[dict[str, str]], model: str | None = None, json_mode: bool = False) -> str:
        payload = {
            "model": model or self.model,
            "messages": messages,
        }

        if json_mode:
            payload["response_format"] = _response_format_for(messages)

        raw = self._request_chat_completion(payload)
        decoded = _decode_openrouter_json(raw)

        if isinstance(decoded, dict) and "error" in decoded:
            raise LLMError(_format_openrouter_api_error(decoded["error"], model=str(payload["model"]), status=None))

        return _content_from_openrouter_response(decoded)

    def _request_chat_completion(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload).encode("utf-8")
        attempts = self.max_retries + 1
        model = str(payload.get("model", self.model))

        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost"),
                    "X-Title": os.getenv("OPENROUTER_SITE_NAME", "SeedFlow CLI"),
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                body_text = _read_http_error_body(exc)
                if _should_retry_http_status(exc.code) and attempt < attempts:
                    _sleep_before_retry(exc.headers, attempt, self.backoff_seconds)
                    continue
                raise LLMError(_format_http_error(exc, body_text, model, attempt, attempts)) from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt < attempts:
                    _sleep_before_retry(None, attempt, self.backoff_seconds)
                    continue
                raise LLMError(_format_network_error(exc, attempt, attempts)) from exc

        raise LLMError("OpenRouter request failed before a response was received.")


def make_llm_client(security: SecurityOptions | None = None) -> LLMClient:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not api_key:
        return MockLLMClient()

    security = security or SecurityOptions()
    base_url = validate_openrouter_base_url(os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL), security)
    return OpenRouterClient(
        api_key=api_key,
        model=default_model(),
        base_url=base_url,
    )


def model_for_tier(tier: str | None) -> str:
    normalized = (tier or "medium").strip().lower()
    env_key = {
        "low": "OPENROUTER_MODEL_LOW",
        "medium": "OPENROUTER_MODEL_MEDIUM",
        "med": "OPENROUTER_MODEL_MEDIUM",
        "high": "OPENROUTER_MODEL_HIGH",
    }.get(normalized, "OPENROUTER_MODEL_MEDIUM")

    return os.getenv(env_key, "").strip() or default_model()


def default_model() -> str:
    return (
        os.getenv("OPENROUTER_MODEL_MEDIUM", "").strip()
        or os.getenv("OPENROUTER_MODEL", "").strip()
        or "google/gemini-3.1-flash-lite-preview"
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()

    if not value:
        return default

    try:
        return max(0, int(value))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()

    if not value:
        return default

    try:
        return max(0.0, float(value))
    except ValueError:
        return default


def _decode_openrouter_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"OpenRouter returned non-JSON response: {_excerpt(raw)}") from exc


def _content_from_openrouter_response(decoded: Any) -> str:
    if not isinstance(decoded, dict):
        raise LLMError(f"OpenRouter response must be a JSON object, got {type(decoded).__name__}.")

    choices = decoded.get("choices")

    if not isinstance(choices, list) or not choices:
        raise LLMError(f"OpenRouter response missing choices[0].message.content: {_excerpt(json.dumps(decoded, ensure_ascii=False))}")

    first = choices[0]

    if not isinstance(first, dict):
        raise LLMError(f"OpenRouter response choice must be an object: {_excerpt(json.dumps(decoded, ensure_ascii=False))}")

    message = first.get("message")

    if not isinstance(message, dict):
        raise LLMError(f"OpenRouter response missing message object: {_excerpt(json.dumps(decoded, ensure_ascii=False))}")

    content = message.get("content")

    if content is None:
        raise LLMError(f"OpenRouter response missing choices[0].message.content: {_excerpt(json.dumps(decoded, ensure_ascii=False))}")

    return str(content)


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _should_retry_http_status(status: int) -> bool:
    return status in {408, 409, 425, 429, 500, 502, 503, 504}


def _sleep_before_retry(headers: Any, attempt: int, backoff_seconds: float) -> None:
    delay = _retry_delay(headers, attempt, backoff_seconds)

    if delay > 0:
        time.sleep(delay)


def _retry_delay(headers: Any, attempt: int, backoff_seconds: float) -> float:
    retry_after = _retry_after_seconds(headers)

    if retry_after is not None:
        return retry_after

    base = backoff_seconds * (2 ** max(0, attempt - 1))

    if base <= 0:
        return 0.0

    return base + random.uniform(0, min(base * 0.25, 1.0))


def _retry_after_seconds(headers: Any) -> float | None:
    if headers is None:
        return None

    value = headers.get("Retry-After") if hasattr(headers, "get") else None

    if not value:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)

        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _format_network_error(exc: BaseException, attempt: int, attempts: int) -> str:
    return f"OpenRouter request failed after {attempt}/{attempts} attempts: {exc}"


def _format_http_error(exc: urllib.error.HTTPError, body_text: str, model: str, attempt: int, attempts: int) -> str:
    detail = _extract_openrouter_error_detail(body_text)
    retry_note = f" after {attempt}/{attempts} attempts" if _should_retry_http_status(exc.code) else ""
    prefix = "OpenRouter rate limited request" if exc.code == 429 else "OpenRouter request failed"
    message = f"{prefix}{retry_note}: HTTP {exc.code} {exc.reason} for model {model}."

    if detail:
        message += f" Detail: {detail}"

    guidance = _http_error_guidance(exc.code, detail, model)

    if guidance:
        message += f" {guidance}"

    return message


def _format_openrouter_api_error(error: Any, model: str, status: int | None) -> str:
    detail = _error_detail_from_value(error)
    status_text = f" HTTP {status}." if status is not None else ""
    message = f"OpenRouter error for model {model}.{status_text}"

    if detail:
        message += f" Detail: {detail}"

    guidance = _http_error_guidance(status, detail, model)

    if guidance:
        message += f" {guidance}"

    return message


def _extract_openrouter_error_detail(body_text: str) -> str:
    if not body_text:
        return ""

    try:
        decoded = json.loads(body_text)
    except json.JSONDecodeError:
        return _excerpt(body_text)

    if isinstance(decoded, dict) and "error" in decoded:
        return _error_detail_from_value(decoded["error"])

    return _error_detail_from_value(decoded)


def _error_detail_from_value(value: Any) -> str:
    if isinstance(value, dict):
        pieces: list[str] = []

        for key in ("message", "code", "type"):
            if value.get(key):
                pieces.append(f"{key}={value[key]}")

        metadata = value.get("metadata")

        if isinstance(metadata, dict):
            for key in ("raw", "provider_name"):
                if metadata.get(key):
                    pieces.append(f"{key}={metadata[key]}")

        return "; ".join(str(piece) for piece in pieces) or _excerpt(json.dumps(value, ensure_ascii=False))

    if isinstance(value, str):
        return value

    return _excerpt(json.dumps(value, ensure_ascii=False))


def _http_error_guidance(status: int | None, detail: str, model: str) -> str:
    lowered = detail.lower()

    if status in {401, 403}:
        return "Check OPENROUTER_API_KEY and account access."

    if status == 404 or "model not found" in lowered or "no endpoints found" in lowered:
        return f"Check that OPENROUTER_MODEL is valid and available: {model}."

    if _looks_like_unsupported_json_mode(lowered):
        return (
            "Rick requires OpenRouter response_format/json_schema for internal JSON calls. "
            "Use a model/provider that supports response_format, or change OPENROUTER_MODEL_MEDIUM/LOW/HIGH."
        )

    if status == 429:
        return "OpenRouter returned rate limit pressure; retry later or lower candidate counts."

    return ""


def _looks_like_unsupported_json_mode(lowered_detail: str) -> bool:
    parameter_markers = ("response_format", "json_schema", "structured_outputs", "require_parameters")
    unsupported_markers = ("unsupported", "not support", "does not support", "invalid parameter", "provider")
    return any(marker in lowered_detail for marker in parameter_markers) and any(marker in lowered_detail for marker in unsupported_markers)


def _excerpt(text: str, limit: int = 1000) -> str:
    stripped = text.strip()

    if len(stripped) <= limit:
        return stripped

    return stripped[:limit] + "..."


def _response_format_for(messages: list[dict[str, str]]) -> dict[str, Any]:
    system_text = "\n".join(message.get("content", "") for message in messages if message.get("role") == "system").lower()
    user_text = "\n".join(message.get("content", "") for message in messages if message.get("role") != "system").lower()
    joined = system_text + "\n" + user_text

    if "hidden judging rubric" in system_text or "define_dod" in system_text:
        return _json_schema_response_format("seedflow_dod", _dod_schema())

    if "candidate generation" in system_text:
        return _json_schema_response_format("seedflow_candidate", _candidate_schema())

    if "selected_index" in joined and "score" in joined and "reason" in joined:
        return _json_schema_response_format("seedflow_judge", _judge_schema())

    if "fallback_used" in joined and '"units"' in joined:
        return _json_schema_response_format("seedflow_explode", _explode_schema())

    return _json_schema_response_format("seedflow_candidate", _candidate_schema())


def _json_schema_response_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def _candidate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "seed": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "random_string": {"type": "string"},
                            "interpretation": {"type": "string"},
                        },
                        "required": ["random_string", "interpretation"],
                    },
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "payload_type": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
                "required": ["seed", "title", "summary", "payload_type", "payload"],
            }
        },
        "required": ["candidate"],
    }


def _judge_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "selected_index": {"type": "integer"},
            "score": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["selected_index", "score", "reason"],
    }


def _dod_schema() -> dict[str, Any]:
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "dod": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "audience": {"type": "string"},
                    "output_language": {"type": "string"},
                    "desired_effect": {"type": "string"},
                    "tone": {"type": "string"},
                    "factual_safety_rules": string_array,
                    "banned_words_or_styles": string_array,
                    "structure_preferences": string_array,
                    "quality_bar": string_array,
                    "final_comment_goal": {"type": "string"},
                },
                "required": [
                    "audience",
                    "output_language",
                    "desired_effect",
                    "tone",
                    "factual_safety_rules",
                    "banned_words_or_styles",
                    "structure_preferences",
                    "quality_bar",
                    "final_comment_goal",
                ],
            }
        },
        "required": ["dod"],
    }


def _explode_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "unit_id": {"type": "string"},
                        "title": {"type": "string"},
                        "source_order": {"type": "integer"},
                        "content": {"type": "string"},
                        "constraints": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "must_preserve": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["unit_id", "title", "source_order", "content", "constraints", "must_preserve"],
                },
            },
            "fallback_used": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["units", "fallback_used", "reason"],
    }


def _ensure_ssl_cert_file() -> None:
    if os.getenv("SSL_CERT_FILE"):
        return

    try:
        import certifi  # type: ignore
    except ImportError:
        return

    os.environ["SSL_CERT_FILE"] = certifi.where()


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()

    if stripped.startswith("```"):
        lines = stripped.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        return "\n".join(lines).strip()

    return stripped


def _extract_json_payload(text: str) -> str:
    stripped = _strip_code_fence(text)
    answer = _strip_code_fence(_extract_answer_payload(stripped))

    if _looks_like_json(answer):
        return answer

    without_thinking = _strip_code_fence(_remove_tagged_block(answer, "thinking"))

    if _looks_like_json(without_thinking):
        return without_thinking

    embedded = _find_first_json_document(without_thinking)

    if embedded:
        return _strip_code_fence(embedded)

    return without_thinking.strip()


def _json_payload_candidates(text: str) -> list[str]:
    raw = text.strip()
    stripped = _strip_code_fence(raw)
    answer = _strip_code_fence(_extract_answer_payload(stripped))
    without_thinking = _strip_code_fence(_remove_tagged_block(answer, "thinking"))
    candidates: list[str] = []

    for value in (answer, without_thinking, stripped, raw, _extract_json_payload(raw)):
        _append_candidate(candidates, value)
        _append_candidate(candidates, _find_first_json_document(value))

    return candidates


def _append_candidate(candidates: list[str], value: str) -> None:
    stripped = value.strip()

    if stripped and stripped not in candidates:
        candidates.append(stripped)


def _loads_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            return json.loads(_repair_common_json_escapes(text), strict=False)


def _repair_common_json_escapes(text: str) -> str:
    return text.replace("\\'", "'")


def _extract_answer_payload(text: str) -> str:
    stripped = text.strip()
    lower = stripped.lower()
    start_tag = "<answer>"
    end_tag = "</answer>"
    start = lower.find(start_tag)

    if start == -1:
        return stripped

    start += len(start_tag)
    end = lower.find(end_tag, start)

    if end == -1:
        return stripped[start:].strip()

    return stripped[start:end].strip()


def _remove_tagged_block(text: str, tag: str) -> str:
    result = text
    tag = tag.lower()
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"

    while True:
        lower = result.lower()
        start = lower.find(start_tag)

        if start == -1:
            return result

        end = lower.find(end_tag, start + len(start_tag))

        if end == -1:
            return (result[:start] + result[start + len(start_tag) :]).strip()

        result = (result[:start] + result[end + len(end_tag) :]).strip()


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _find_first_json_document(text: str) -> str:
    for start, char in enumerate(text):
        if char not in "{[":
            continue

        extracted = _balanced_json_from(text, start)

        if extracted:
            return extracted

    return ""


def _balanced_json_from(text: str, start: int) -> str:
    stack: list[str] = []
    in_string = False
    escaped = False
    pairs = {"{": "}", "[": "]"}

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char in pairs:
            stack.append(pairs[char])
            continue

        if char in "}]":
            if not stack or stack[-1] != char:
                return ""

            stack.pop()

            if not stack:
                return text[start : index + 1].strip()

    return ""
