"""Mock-only Cloud Run entry: persist the whole acceptance artifact to private GCS."""
import json
import os
import re
from pathlib import Path
from urllib.parse import quote
from . import net
from .smoke import run

def main() -> None:
    bucket = os.environ.get("RCWG_ARTIFACT_BUCKET", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", bucket) or "REPLACE" in bucket:
        raise ValueError("Configure a private artifact bucket before running the cloud job")
    if not os.environ.get("CLOUD_RUN_EXECUTION"):
        raise ValueError("This entry is for Cloud Run Jobs; use `smoke` for local runs")
    report, _ = run(Path("/tmp/rcwg-runs"))
    execution = os.environ["CLOUD_RUN_EXECUTION"]
    if not re.fullmatch(r"[a-z0-9-]{1,100}", execution):
        raise ValueError("Unexpected execution ID")
    name = "boot/" + execution + "/" + report["attempt_id"] + "/report.json"
    token_response = net.request_json(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        None, {"Metadata-Flavor": "Google"}, method="GET")
    token = token_response["access_token"]
    uploaded = net.request_json(
        "https://storage.googleapis.com/upload/storage/v1/b/" + quote(bucket, safe="") +
        "/o?uploadType=media&ifGenerationMatch=0&name=" + quote(name, safe=""),
        report, {"Authorization": "Bearer " + token})
    print(json.dumps({"status": "PERSISTED", "scope": "BOOT_ONLY", "api_requests": 0,
                      "artifact": "gs://" + bucket + "/" + name,
                      "generation": uploaded.get("generation")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
