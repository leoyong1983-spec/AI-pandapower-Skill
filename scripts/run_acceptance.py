from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_pandapower_skill import assess_grid


ARTIFACT_NAMES = ("grid_result.json", "violations.json", "grid_summary.md", "calculation_log.md")
LOCAL_ABSOLUTE_PATH = re.compile(r"(^|[^A-Za-z])[A-Za-z]:[\\/]")


CASES = [
    {
        "name": "demo_grid",
        "input": "examples/demo_grid.json",
        "classification": "success",
        "checks": {
            "line_overload_count_min": 1,
            "voltage_violation_count_min": 1,
        },
    },
    {
        "name": "missing_parameter",
        "input": "examples/bad_missing_parameter.json",
        "classification": "missing_parameter",
        "checks": {},
    },
    {
        "name": "input_error",
        "input": "examples/bad_input_reference.json",
        "classification": "input_error",
        "checks": {},
    },
    {
        "name": "island_network",
        "input": "examples/bad_island_network.json",
        "classification": "island_network",
        "checks": {},
    },
    {
        "name": "non_convergent",
        "input": "examples/bad_non_convergent.json",
        "classification": "power_flow_not_converged",
        "checks": {},
    },
    {
        "name": "missing_dependency",
        "input": "examples/demo_grid.json",
        "classification": "missing_dependency",
        "checks": {},
        "force_missing_dependency": True,
    },
]


def main() -> int:
    out_root = ROOT / "outputs" / "acceptance"
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    report = []
    for case in CASES:
        output_dir = out_root / case["name"]
        old_force = os.environ.get("AI_PANDAPOWER_FORCE_MISSING_DEPENDENCY")
        if case.get("force_missing_dependency"):
            os.environ["AI_PANDAPOWER_FORCE_MISSING_DEPENDENCY"] = "1"
        else:
            os.environ.pop("AI_PANDAPOWER_FORCE_MISSING_DEPENDENCY", None)
        try:
            result = assess_grid(ROOT / case["input"], output_dir)
        finally:
            if old_force is None:
                os.environ.pop("AI_PANDAPOWER_FORCE_MISSING_DEPENDENCY", None)
            else:
                os.environ["AI_PANDAPOWER_FORCE_MISSING_DEPENDENCY"] = old_force
        row = {
            "case": case["name"],
            "status": result["status"],
            "classification": result["classification"],
            "output_dir": _relative(output_dir),
        }
        if result["classification"] != case["classification"]:
            failures.append(f"{case['name']}: expected {case['classification']}, got {result['classification']}")
        if result["status"] == "success":
            summary = result["summary"]
            if summary["line_overload_count"] < case["checks"].get("line_overload_count_min", 0):
                failures.append(f"{case['name']}: expected at least one line overload")
            if summary["voltage_violation_count"] < case["checks"].get("voltage_violation_count_min", 0):
                failures.append(f"{case['name']}: expected at least one voltage violation")
        for artifact_name in ARTIFACT_NAMES:
            artifact_path = output_dir / artifact_name
            if not artifact_path.exists():
                failures.append(f"{case['name']}: missing artifact {artifact_name}")
                continue
            artifact_text = artifact_path.read_text(encoding="utf-8")
            if LOCAL_ABSOLUTE_PATH.search(artifact_text):
                failures.append(f"{case['name']}: local absolute path leaked in {artifact_name}")
        report.append(row)

    print(json.dumps({"cases": report, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    raise SystemExit(main())
