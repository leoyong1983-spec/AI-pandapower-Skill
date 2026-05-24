from __future__ import annotations

import importlib
import importlib.metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "requirements.txt",
    "ai_pandapower_skill/runner.py",
    "scripts/run_grid_assessment.py",
    "scripts/run_acceptance.py",
    "schemas/input_schema.json",
    "schemas/output_schema.json",
)


def main() -> int:
    checks: list[dict[str, object]] = []

    for file_name in REQUIRED_FILES:
        path = ROOT / file_name
        checks.append({"name": f"file:{file_name}", "ok": path.exists() and path.is_file()})

    for schema_name in ("schemas/input_schema.json", "schemas/output_schema.json"):
        try:
            json.loads((ROOT / schema_name).read_text(encoding="utf-8"))
            checks.append({"name": f"schema-json:{schema_name}", "ok": True})
        except Exception as exc:
            checks.append({"name": f"schema-json:{schema_name}", "ok": False, "message": str(exc)})

    try:
        importlib.import_module("ai_pandapower_skill.runner")
        checks.append({"name": "runner-import-without-side-effects", "ok": True})
    except Exception as exc:
        checks.append({"name": "runner-import-without-side-effects", "ok": False, "message": str(exc)})

    try:
        version = importlib.metadata.version("pandapower")
        checks.append({"name": "dependency:pandapower", "ok": version == "3.4.0", "version": version})
    except importlib.metadata.PackageNotFoundError:
        checks.append({"name": "dependency:pandapower", "ok": False, "message": "pandapower is not installed"})

    ok = all(bool(check["ok"]) for check in checks)
    print(json.dumps({"status": "ready" if ok else "not_ready", "checks": checks}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

