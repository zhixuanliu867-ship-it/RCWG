import argparse
import json
from pathlib import Path
from .api_probe import probe
from .checks import check, formal_gate
from .common import write_json
from .doctor import collect
from .smoke import run

def main() -> int:
    parser = argparse.ArgumentParser(description="RCWG-BOOT-001 environment acceptance tools")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor"); p.add_argument("--out", type=Path, default=Path("runs/doctor.json"))
    p = sub.add_parser("check"); p.add_argument("--formal", action="store_true")
    p = sub.add_parser("smoke"); p.add_argument("--out", type=Path, default=Path("runs"))
    p = sub.add_parser("api-probe")
    p.add_argument("--provider", choices=["mock", "gemini", "dashscope"], default="mock")
    p.add_argument("--model", default="UNRESOLVED")
    p.add_argument("--allow-paid", action="store_true")
    p.add_argument("--reserve-usd")
    p.add_argument("--base-url")
    p.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            report = collect(); write_json(args.out, report)
            print(json.dumps({"status": "COLLECTED", "report": str(args.out)}, ensure_ascii=False)); return 0
        if args.command == "check":
            report = formal_gate() if args.formal else check()
            print(json.dumps(report, ensure_ascii=False, indent=2)); return 2 if args.formal else 0
        if args.command == "smoke":
            report, path = run(args.out)
        else:
            report, path = probe(args.provider, args.model, args.out, allow_paid=args.allow_paid,
                                 reserve_usd=args.reserve_usd, base_url=args.base_url)
        print(json.dumps({"status": report["status"], "report": str(path)}, ensure_ascii=False))
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, "BOOT_ERROR: " + str(exc) + "\n")

if __name__ == "__main__":
    raise SystemExit(main())
