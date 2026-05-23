---
name: ai-pandapower-skill
description: Validate grid JSON input, run pandapower load flow, classify input/convergence/island failures, detect voltage and thermal violations, and export evidence artifacts.
version: 0.1.0
---

## Purpose

Use this skill when an agent needs to control pandapower through a script-first workflow and produce auditable evidence files.

## Workflow

1. Prepare a grid input JSON with these top-level sections:
   - `bus`
   - `line`
   - `transformer`
   - `load`
   - `generator`
   - `grid_connection`
   - optional `settings`
2. Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_grid_assessment.py --input examples\demo_grid.json --output-dir outputs\demo_grid
```

3. Inspect the four evidence files in the output directory:
   - `grid_result.json`
   - `violations.json`
   - `grid_summary.md`
   - `calculation_log.md`

4. For regression acceptance, run:

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
```

## Failure Classification

- `missing_parameter`: required section or field is absent.
- `input_error`: JSON shape, numeric type, duplicate id, invalid value, or unknown bus reference is invalid.
- `island_network`: one or more buses are not connected to any in-service `grid_connection`.
- `power_flow_not_converged`: pandapower `runpp` fails to converge after valid input and topology checks.
- `runtime_error`: unexpected runtime failure; artifacts are still written.

## Evidence Contract

Every run must write the same four files. Downstream tools should treat `grid_result.json` as the manifest and `violations.json` as the machine-readable violation list.

## Extension Rules

Do not bypass the existing validation and artifact export path. Add future modules, such as short circuit, protection settings, dynamic stability, N-1, and GIS import, as adapters around the same stable input/output contract unless a new contract is explicitly versioned.

