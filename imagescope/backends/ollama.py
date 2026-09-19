"""Ollama transport and Qwen JSON-continuation adapter. No model downloads."""
import base64
import io
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ..contracts import AnalyzerError, DEFAULT_ENDPOINT, strict_json_loads
from ..profiles.wallpaper import SCHEMA, VISION_PROMPT, validate_description, clean_description

JSON_PREFIX = '{"caption":'


class VisionResponseError(AnalyzerError, ValueError):
    def __init__(self, message, details):
        super().__init__('invalid_response', message, details)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaBackend:
    name = 'ollama'

    def __init__(self, endpoint=DEFAULT_ENDPOINT, timeout=300, keep_alive=300, transport=None):
        parsed = urlparse(endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AnalyzerError('invalid_request', 'Endpoint must be an HTTP(S) API URL without credentials, query, or fragment')
        self.endpoint = endpoint.rstrip('/') + '/'
        self.deadline = time.monotonic() + timeout
        self.keep_alive = keep_alive
        self.transport = transport
        self.identities = {}

    def request(self, endpoint, payload=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AnalyzerError('timeout', 'Analyzer request timed out')
        if self.transport:
            return self.transport(endpoint, payload)
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.endpoint + endpoint, data=data, headers={'Content-Type':'application/json'})
        try:
            with build_opener(NoRedirect).open(request, timeout=remaining) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if time.monotonic() > self.deadline:
                raise AnalyzerError('timeout', 'Analyzer request timed out')
            if len(data) > 2 * 1024 * 1024:
                raise AnalyzerError('invalid_response', 'Ollama response exceeds the 2 MiB limit')
            value = strict_json_loads(data)
            if not isinstance(value, dict):
                raise ValueError('Expected a JSON object')
            return value
        except HTTPError as exc:
            raise AnalyzerError('backend_error', f'Ollama returned HTTP {exc.code}') from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AnalyzerError('timeout', 'Ollama request timed out') from exc
        except URLError as exc:
            code = 'timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'backend_unavailable'
            raise AnalyzerError(code, f'Cannot reach Ollama: {exc.reason}') from exc
        except (ValueError, UnicodeError) as exc:
            raise AnalyzerError('invalid_response', 'Ollama returned invalid JSON') from exc

    def check_model(self, model):
        if model not in self.identities:
            models = self.request('tags').get('models', [])
            if not isinstance(models, list) or not all(isinstance(m, dict) for m in models):
                raise AnalyzerError('invalid_response', 'Ollama returned an invalid model inventory')
            identity = next((m for m in models if m.get('name') == model), None)
            if identity is None:
                raise AnalyzerError('model_missing', f'Model not installed: {model}. Install it explicitly with: ollama pull {model}')
            self.identities[model] = (identity, self.request('version'))
        return self.identities[model]

    def settings(self, preview_size):
        return {'preview_size': preview_size, 'json_prefix': JSON_PREFIX,
                'think': False, 'num_ctx': 4096, 'num_predict': 1024,
                'temperature': 0, 'seed': 42, 'keep_alive': self.keep_alive}

    def describe(self, image, model, preview_size):
        return describe_image(image, model, preview_size, transport=self.request, keep_alive=self.keep_alive)


def describe_image(image, model, preview_size=768, *, transport, keep_alive=300):
    preview = image.copy()
    preview.thumbnail((preview_size, preview_size))
    buffer = io.BytesIO()
    preview.save(buffer, format="JPEG", quality=90)
    response = transport("chat", {
        "model": model, "stream": False, "think": False, "format": SCHEMA,
        "messages": [{"role": "user", "content": VISION_PROMPT,
                      "images": [base64.b64encode(buffer.getvalue()).decode()]},
                     {"role": "assistant", "content": JSON_PREFIX}],
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 1024},
        "keep_alive": keep_alive,
    })
    if not isinstance(response, dict) or not isinstance(response.get("message", {}), dict):
        raise VisionResponseError("Invalid model response envelope", {})
    message = response.get("message", {})
    content = message.get("content", "")
    details = {
        "ollama_timing_ns": {key: response.get(key) for key in
                             ["total_duration", "load_duration", "prompt_eval_duration", "eval_duration", "eval_count", "prompt_eval_count"]},
        "vision_response": {"done_reason": response.get("done_reason"),
                            "thinking_chars": len(str(message.get("thinking", ""))),
                            "preview_width": preview.width, "preview_height": preview.height},
    }
    try:
        if response.get("done_reason") == "length":
            raise ValueError("Model exhausted the output token budget before completing JSON")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Model returned no final JSON content")
        # Ollama may return a continuation or a complete object. Never parse thinking.
        text = content.lstrip()
        description = validate_description(strict_json_loads(text if text.startswith("{") else JSON_PREFIX + content))
    except (ValueError, TypeError) as exc:
        details["vision_response"]["content"] = str(content)[:8192]
        raise VisionResponseError(str(exc), details) from exc
    cleaned = clean_description(description)
    if cleaned != description:
        details["vision_raw"] = description
    return cleaned, details

