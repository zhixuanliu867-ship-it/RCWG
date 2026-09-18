"""Explicitly opt-in single-call connectivity probe; never used for formal generation."""
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from . import net
from .budget import finish, reserve
from .common import digest, now_utc, write_json

PROMPT = 'Return exactly the JSON object {"ok": true}. Do not add commentary.'
LEGACY_HOSTS = {"dashscope-intl.aliyuncs.com", "dashscope.aliyuncs.com", "dashscope-us.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com"}

def endpoint(provider: str, model: str, base_url: str | None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
        raise ValueError("Use the exact provider model ID, without slashes or URL syntax")
    if provider == "gemini":
        if base_url:
            raise ValueError("Gemini probe uses its fixed official endpoint")
        return "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
    if provider != "dashscope" or not base_url:
        raise ValueError("DashScope requires a console-confirmed compatible-mode base URL")
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    workspace = re.fullmatch(r"[a-zA-Z0-9-]+\.(ap-southeast-1|cn-beijing|cn-hongkong|ap-northeast-1|us-east-1)\.maas\.aliyuncs\.com", host)
    if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment or parts.port not in (None, 443):
        raise ValueError("Endpoint must be HTTPS without credentials, query, fragment or nonstandard port")
    if host not in LEGACY_HOSTS and not workspace:
        raise ValueError("Endpoint host is outside the reviewed Alibaba allowlist")
    if parts.path.rstrip("/") != "/compatible-mode/v1":
        raise ValueError("Expected a compatible-mode/v1 base URL")
    return base_url.rstrip("/") + "/chat/completions"

def probe(provider: str, model: str, output_root: Path, *, allow_paid: bool = False,
          reserve_usd: str | None = None, base_url: str | None = None,
          ledger: Path | None = None) -> tuple[dict, Path]:
    if provider == "mock":
        data = {"status": "PASS", "provider": "mock", "api_requests": 0,
                "scope": "CONNECTIVITY_ONLY", "actual_cost_usd": 0,
                "remote_gpu_ns": None, "formal_result": False}
        path = output_root / ("mock-probe-" + uuid.uuid4().hex) / "report.json"
        write_json(path, data)
        return data, path
    if not allow_paid or reserve_usd is None:
        raise ValueError("Live probe requires --allow-paid and --reserve-usd; default mode is mock")
    if os.environ.get("CLOUD_RUN_EXECUTION") or os.environ.get("CLOUD_RUN_JOB"):
        raise ValueError("BOOT live probes run only on the owner-approved local shell")
    url = endpoint(provider, model, base_url)
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "DASHSCOPE_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        raise ValueError("Required key environment variable is not set: " + key_name)
    if provider == "gemini":
        payload = {"contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
                   "generationConfig": {"temperature": 0, "maxOutputTokens": 128, "responseMimeType": "application/json"}}
        headers = {"x-goog-api-key": key}
    else:
        payload = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
                   "temperature": 0, "max_tokens": 128, "stream": False, "enable_thinking": False}
        headers = {"Authorization": "Bearer " + key}
    # API reservation is persisted BEFORE network access. Never automatically refunded.
    ledger = ledger or Path.home() / ".local/state/rcwg-boot-001/probes.sqlite3"
    rid = reserve(ledger, reserve_usd)
    report = {"ticket": "RCWG-BOOT-001", "scope": "CONNECTIVITY_ONLY", "provider": provider,
              "requested_model": model, "reported_model": None, "created_at_utc": now_utc(),
              "reservation_id": rid, "reserved_usd": reserve_usd, "actual_cost_usd": None,
              "reservation_is_billing_cap": False, "prompt_sha256": digest(PROMPT),
              "request_sha256": digest(payload), "api_requests": 1, "retries": 0,
              "remote_gpu_ns": None, "remote_cpu_ns": None, "remote_vram_bytes": None,
              "formal_result": False, "status": "FAILED", "usage": None}
    start = time.perf_counter_ns()
    try:
        response = net.request_json(url, payload, headers)
        report["response_sha256"] = digest(response)
        if provider == "gemini":
            text = "".join(p.get("text", "") for p in response["candidates"][0]["content"]["parts"] if not p.get("thought"))
            report["usage"] = response.get("usageMetadata")
            report["reported_model"] = response.get("modelVersion")
        else:
            text = response["choices"][0]["message"]["content"]
            report["usage"] = response.get("usage")
            report["reported_model"] = response.get("model")
        decoded = json.loads(text)
        exact = isinstance(decoded, dict) and set(decoded) == {"ok"} and decoded["ok"] is True
        report["status"] = "PASS" if exact else "SCHEMA_MISMATCH"
    except (RuntimeError, ValueError, KeyError, IndexError, TypeError) as exc:
        # No exception text from remote data is recorded.
        report["error_kind"] = type(exc).__name__
        if isinstance(exc, RuntimeError) and re.fullmatch(r"HTTP_STATUS_[0-9]{3}|NETWORK_OR_TIMEOUT_ERROR", str(exc)):
            report["error_code"] = str(exc)
    finally:
        report["client_latency_ns"] = time.perf_counter_ns() - start
        finish(ledger, rid, report["status"])
    path = output_root / ("api-probe-" + rid) / "report.json"
    write_json(path, report)
    return report, path
