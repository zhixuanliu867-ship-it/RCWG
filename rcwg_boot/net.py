"""Bounded, one-attempt HTTP primitives. Credential-bearing redirects are denied."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def request_json(url: str, payload: dict | None, headers: dict, *, method: str = "POST") -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method=method)
    opener = build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=30) as response:
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("Response exceeds 1 MiB bootstrap limit")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object response")
            return value
    except HTTPError as exc:
        # Do not dump remote response bodies, keys, headers or signed URLs.
        raise RuntimeError("HTTP_STATUS_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("NETWORK_OR_TIMEOUT_ERROR") from None
