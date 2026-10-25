"""Local OpenAI-compatible reverse proxy for Gemini Code Assist (Antigravity OAuth).

Bridges the TextTo3D backend's OpenAI-style LLM client onto the local
Antigravity OAuth credentials so free-form CAD planning can run on Gemini:

- Reads the refresh token from ``~/.gemini/oauth_creds.json``
  (env ``GEMINI_OAUTH_CREDS`` overrides the path).
- Refreshes access tokens with the Antigravity desktop app's public OAuth
  client credentials (the same values embedded in every installed copy; they
  are not user secrets). ``GEMINI_CLIENT_ID``/``GEMINI_CLIENT_SECRET`` override.
- Translates ``POST /v1/chat/completions`` (OpenAI) to the Code Assist
  ``v1internal:streamGenerateContent?alt=sse`` endpoint and aggregates the
  SSE parts back into one OpenAI chat completion.
- Google endpoints need the local system proxy on this machine; default
  ``GEMINI_PROXY_HTTP=http://127.0.0.1:12450`` (set ``none`` to disable).

Run standalone (``python gemini_proxy.py``) or via ``start_gemini_proxy.bat``.
The TextTo3D backend only needs::

    LLM_API_URL=http://127.0.0.1:8799/v1/chat/completions
    LLM_MODEL=gemini-2.5-flash
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.getenv("GEMINI_PROXY_PORT", "8799"))
DEFAULT_MODEL = os.getenv("GEMINI_PROXY_MODEL", "models/gemini-2.5-flash")
CREDS_PATH = Path(os.getenv(
    "GEMINI_OAUTH_CREDS",
    Path.home() / ".gemini" / "oauth_creds.json",
))
# Public client credentials embedded in the Antigravity desktop install
# (shipped in every copy of resources/bin/language_server.exe; not user data).
CLIENT_ID = os.getenv("GEMINI_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GEMINI_CLIENT_SECRET", "")
UPSTREAM = os.getenv(
    "GEMINI_CODE_ASSIST_URL",
    "https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse",
)
UPSTREAM_HEADERS = {
    "Content-Type": "application/json",
    # The license check (#3501) passes only for the SSE endpoint with the
    # Antigravity client identification headers.
    "x-goog-api-client": "antigravity/1.104.0",
    "User-Agent": "Antigravity (Windows 10) antigravity/1.104.0",
}
_proxy_env = os.getenv("GEMINI_PROXY_HTTP", "http://127.0.0.1:12450")
OPENER = (
    urllib.request.build_opener()
    if _proxy_env.lower() in {"none", "off", "direct"}
    else urllib.request.build_opener(urllib.request.ProxyHandler({
        "http": _proxy_env, "https": _proxy_env,
    }))
)

ERROR_HINTS = {
    401: "token refresh failed; run any Antigravity app once to refresh credentials",
    403: "license check rejected; update the client version headers",
    429: "Gemini daily quota exhausted for this Google account; retries after the quota reset",
}
# The free Antigravity tier also enforces a per-minute rate limit that trips
# intermittently under burst load; brief spaced retries smooth it out.
RETRY_STATUS = {429, 500, 502, 503}
RETRY_DELAYS = [float(d) for d in os.getenv("GEMINI_PROXY_RETRY_DELAYS", "4,10").split(",") if d.strip()]


class TokenManager:
    """Refresh Antigravity OAuth access tokens with a small expiry margin."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._expires_at:
                return self._token
            creds = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
            body = urllib.parse.urlencode({
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            }).encode()
            request = urllib.request.Request(
                "https://oauth2.googleapis.com/token", data=body, method="POST"
            )
            with OPENER.open(request, timeout=30) as response:
                payload = json.load(response)
            self._token = str(payload["access_token"])
            self._expires_at = time.time() + float(payload.get("expires_in", 3600)) - 120.0
            return self._token


TOKENS = TokenManager()


def _translate_request(body: dict) -> dict:
    """OpenAI chat payload -> Code Assist generateContent payload."""
    system_parts: list[str] = []
    contents: list[dict] = []
    for message in body.get("messages") or []:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        content = str(content)
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        contents.append({"role": "model" if role == "assistant" else "user",
                         "parts": [{"text": content}]})
    generation_config: dict = {}
    if body.get("temperature") is not None:
        generation_config["temperature"] = float(body["temperature"])
    if isinstance(body.get("response_format"), dict) and body["response_format"].get("type") == "json_object":
        generation_config["responseMimeType"] = "application/json"
    model = str(body.get("model") or DEFAULT_MODEL)
    if not model.startswith("models/"):
        model = "models/" + model
    request: dict = {"contents": contents, "generationConfig": generation_config}
    if system_parts:
        request["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    return {"model": model, "project": "", "request": request}


def _parse_sse(raw: str) -> tuple[str, dict, str]:
    text_parts: list[str] = []
    usage: dict = {}
    finish_reason = "stop"
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            chunk = json.loads(line[6:])
        except (json.JSONDecodeError, ValueError):
            continue
        usage.update(chunk.get("usageMetadata") or {})
        for candidate in chunk.get("candidates") or []:
            finish_reason = str(candidate.get("finishReason") or finish_reason)
            for part in candidate.get("content", {}).get("parts") or []:
                text_parts.append(str(part.get("text", "")))
    return "".join(text_parts), usage, finish_reason


def chat_completions(body: dict) -> tuple[int, dict]:
    payload = _translate_request(body)
    delays = list(RETRY_DELAYS)
    for force in (False, True):
        while True:
            request = urllib.request.Request(
                UPSTREAM,
                data=json.dumps(payload).encode("utf-8"),
                headers={**UPSTREAM_HEADERS, "Authorization": f"Bearer {TOKENS.get(force=force)}"},
                method="POST",
            )
            try:
                with OPENER.open(request, timeout=180) as response:
                    text, usage, finish_reason = _parse_sse(response.read().decode("utf-8", "ignore"))
                return 200, {
                    "id": "gemini-proxy",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": payload["model"],
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": finish_reason,
                    }],
                    "usage": {
                        "prompt_tokens": int(usage.get("promptTokenCount", 0)),
                        "completion_tokens": int(usage.get("candidatesTokenCount", 0)),
                        "total_tokens": int(usage.get("totalTokenCount", 0)),
                    },
                }
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "ignore")
                message = detail
                try:
                    message = str(json.loads(detail).get("error", {}).get("message", detail))
                except (json.JSONDecodeError, ValueError):
                    pass
                if exc.code == 401 and not force:
                    break  # stale token: force one refresh and retry
                if exc.code in RETRY_STATUS and delays:
                    time.sleep(delays.pop(0))
                    continue
                hint = ERROR_HINTS.get(exc.code, "")
                return exc.code, {"error": {
                    "message": f"Gemini upstream HTTP {exc.code}: {message}" + (f" ({hint})" if hint else ""),
                    "type": "upstream_error",
                    "code": exc.code,
                }}
            except (urllib.error.URLError, TimeoutError) as exc:
                if delays:
                    time.sleep(delays.pop(0))
                    continue
                return 502, {"error": {
                    "message": f"Gemini upstream unreachable via {_proxy_env}: {exc}",
                    "type": "proxy_error",
                    "code": 502,
                }}
        force = True
    return 500, {"error": {"message": "token refresh loop", "type": "auth_error", "code": 500}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quiet default access log
        pass

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path in ("/health", "/"):
            self._send(200, {"status": "ok", "model": DEFAULT_MODEL, "proxy": _proxy_env})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/v1/chat/completions":
            self._send(404, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, ValueError) as exc:
            self._send(400, {"error": {"message": f"invalid JSON body: {exc}"}})
            return
        self._send(*chat_completions(body))


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"gemini proxy listening on http://127.0.0.1:{PORT} "
          f"(model={DEFAULT_MODEL}, upstream via {_proxy_env})")
    server.serve_forever()


if __name__ == "__main__":
    main()
