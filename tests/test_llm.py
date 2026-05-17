from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from seedflow_cli.llm import (
    LLMError,
    OpenRouterClient,
    _json_payload_candidates,
    _response_format_for,
)


class StaticOpenRouterClient(OpenRouterClient):
    def __init__(self, text: str) -> None:
        self.text = text

    def _chat(self, messages, model=None, json_mode=False):  # noqa: ANN001
        return self.text


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        return self.payload


def http_error(status: int, reason: str, body: str, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=status,
        msg=reason,
        hdrs=headers or {},
        fp=io.BytesIO(body.encode("utf-8")),
    )


class LLMTests(unittest.TestCase):
    def test_json_payload_candidates_extract_answer_and_remove_thinking(self) -> None:
        text = '<thinking>{"ignore": true}</thinking><answer>{"candidate":{"title":"ok"}}</answer>'

        candidates = _json_payload_candidates(text)

        self.assertIn('{"candidate":{"title":"ok"}}', candidates)
        self.assertNotIn('{"ignore": true}', candidates[0])

    def test_json_payload_candidates_find_embedded_balanced_json(self) -> None:
        text = 'prefix {"outer": {"inner": [1, {"two": 2}]}} suffix'

        candidates = _json_payload_candidates(text)

        self.assertIn('{"outer": {"inner": [1, {"two": 2}]}}', candidates)

    def test_chat_json_accepts_fenced_or_wrapped_json(self) -> None:
        client = StaticOpenRouterClient('```json\n{"selected_index":0,"score":90,"reason":"ok"}\n```')

        self.assertEqual(client.chat_json([])["score"], 90)

    def test_chat_seeded_json_extracts_json_from_answer_tags(self) -> None:
        client = StaticOpenRouterClient(
            '<random_string>abc</random_string><thinking>sum-mod</thinking><answer>{"candidate":{"title":"ok"}}</answer>'
        )

        self.assertEqual(client.chat_seeded_json([])["candidate"]["title"], "ok")

    def test_chat_seeded_json_accepts_literal_newlines_inside_json_strings(self) -> None:
        client = StaticOpenRouterClient('```json\n{"candidate":{"payload":{"markdown":"line one\nline two"}}}\n```')

        self.assertEqual(client.chat_seeded_json([])["candidate"]["payload"]["markdown"], "line one\nline two")

    def test_chat_seeded_json_repairs_escaped_single_quotes(self) -> None:
        client = StaticOpenRouterClient('{"candidate":{"summary":"it\\\'s playable"}}')

        self.assertEqual(client.chat_seeded_json([])["candidate"]["summary"], "it's playable")

    def test_chat_json_raises_on_invalid_json(self) -> None:
        client = StaticOpenRouterClient("not json")

        with self.assertRaisesRegex(LLMError, "invalid JSON"):
            client.chat_json([])

    def test_response_format_routes_known_internal_prompts_to_schemas(self) -> None:
        judge_format = _response_format_for(
            [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": '{"selected_index":0,"score":0,"reason":"x"}'},
            ]
        )
        candidate_format = _response_format_for(
            [
                {"role": "system", "content": "For candidate generation, return JSON."},
                {"role": "user", "content": "Generate a candidate."},
            ]
        )
        dod_format = _response_format_for(
            [
                {"role": "system", "content": "This is a hidden judging rubric."},
                {"role": "user", "content": "Define DoD."},
            ]
        )

        self.assertEqual(judge_format["json_schema"]["name"], "seedflow_judge")
        self.assertEqual(candidate_format["json_schema"]["name"], "seedflow_candidate")
        self.assertEqual(dod_format["json_schema"]["name"], "seedflow_dod")

    def test_openrouter_retries_rate_limit_then_returns_content(self) -> None:
        client = OpenRouterClient("key", "model/test", max_retries=1, backoff_seconds=0)
        success = FakeResponse('{"choices":[{"message":{"content":"ok"}}]}')

        with patch(
            "seedflow_cli.llm.urllib.request.urlopen",
            side_effect=[
                http_error(429, "Too Many Requests", '{"error":{"message":"rate limited"}}'),
                success,
            ],
        ) as urlopen:
            self.assertEqual(client.chat_text([{"role": "user", "content": "hello"}]), "ok")

        self.assertEqual(urlopen.call_count, 2)

    def test_openrouter_does_not_retry_auth_errors(self) -> None:
        client = OpenRouterClient("bad-key", "model/test", max_retries=3, backoff_seconds=0)

        with patch(
            "seedflow_cli.llm.urllib.request.urlopen",
            side_effect=http_error(401, "Unauthorized", '{"error":{"message":"invalid key"}}'),
        ) as urlopen:
            with self.assertRaisesRegex(LLMError, "Check OPENROUTER_API_KEY"):
                client.chat_text([{"role": "user", "content": "hello"}])

        self.assertEqual(urlopen.call_count, 1)

    def test_openrouter_reports_retry_exhaustion_with_body_detail(self) -> None:
        client = OpenRouterClient("key", "model/test", max_retries=1, backoff_seconds=0)

        with patch(
            "seedflow_cli.llm.urllib.request.urlopen",
            side_effect=[
                http_error(500, "Server Error", '{"error":{"message":"upstream down","code":"provider_error"}}'),
                http_error(500, "Server Error", '{"error":{"message":"still down"}}'),
            ],
        ):
            with self.assertRaisesRegex(LLMError, "after 2/2 attempts.*still down"):
                client.chat_text([{"role": "user", "content": "hello"}])

    def test_openrouter_reports_unsupported_json_mode_guidance(self) -> None:
        client = OpenRouterClient("key", "model/no-json", max_retries=0)
        body = '{"error":{"message":"Provider does not support response_format"}}'

        with patch("seedflow_cli.llm.urllib.request.urlopen", side_effect=http_error(400, "Bad Request", body)):
            with self.assertRaisesRegex(LLMError, "requires OpenRouter response_format/json_schema"):
                client.chat_json([{"role": "user", "content": "hello"}])

    def test_chat_seeded_json_does_not_send_response_format(self) -> None:
        client = OpenRouterClient("key", "model/test", max_retries=0)
        response = FakeResponse(
            '{"choices":[{"message":{"content":"<answer>{\\"candidate\\":{\\"title\\":\\"ok\\"}}</answer>"}}]}'
        )

        with patch("seedflow_cli.llm.urllib.request.urlopen", return_value=response) as urlopen:
            result = client.chat_seeded_json([{"role": "user", "content": "hello"}])

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("response_format", payload)
        self.assertEqual(result["candidate"]["title"], "ok")

    def test_openrouter_reports_non_json_success_response(self) -> None:
        client = OpenRouterClient("key", "model/test", max_retries=0)

        with patch("seedflow_cli.llm.urllib.request.urlopen", return_value=FakeResponse("<html>bad gateway</html>")):
            with self.assertRaisesRegex(LLMError, "non-JSON response"):
                client.chat_text([{"role": "user", "content": "hello"}])

    def test_openrouter_reports_missing_content_shape(self) -> None:
        client = OpenRouterClient("key", "model/test", max_retries=0)

        with patch("seedflow_cli.llm.urllib.request.urlopen", return_value=FakeResponse('{"choices":[]}')):
            with self.assertRaisesRegex(LLMError, "missing choices\\[0\\]\\.message\\.content"):
                client.chat_text([{"role": "user", "content": "hello"}])

    def test_openrouter_retries_network_errors(self) -> None:
        client = OpenRouterClient("key", "model/test", max_retries=1, backoff_seconds=0)

        with patch(
            "seedflow_cli.llm.urllib.request.urlopen",
            side_effect=[
                urllib.error.URLError("temporary DNS failure"),
                FakeResponse('{"choices":[{"message":{"content":"ok"}}]}'),
            ],
        ) as urlopen:
            self.assertEqual(client.chat_text([{"role": "user", "content": "hello"}]), "ok")

        self.assertEqual(urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
