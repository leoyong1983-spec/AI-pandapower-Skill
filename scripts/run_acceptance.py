from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_pandapower_skill import assess_grid


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
        result = assess_grid(ROOT / case["input"], output_dir)
        row = {
            "case": case["name"],
            "status": result["status"],
            "classification": result["classification"],
            "output_dir": str(output_dir),
        }
        if result["classification"] != case["classification"]:
            failures.append(f"{case['name']}: expected {case['classification']}, got {result['classification']}")
        if result["status"] == "success":
            summary = result["summary"]
            if summary["line_overload_count"] < case["checks"].get("line_overload_count_min", 0):
                failures.append(f"{case['name']}: expected at least one line overload")
            if summary["voltage_violation_count"] < case["checks"].get("voltage_violation_count_min", 0):
                failures.append(f"{case['name']}: expected at least one voltage violation")
        report.append(row)

    print(json.dumps({"cases": report, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

