# AI pandapower Skill

This repository provides a small, auditable pandapower automation layer for grid validation, load-flow calculation, violation detection, and evidence export.

The current release is a baseline Trinity integration gate. It intentionally covers load-flow and violation review only; short circuit, protection settings, dynamic stability, complex N-1, and GIS import remain out of scope for this hardening pass.

## Current Capability

Supported input sections:

- `bus`: bus id, name, voltage level `vn_kv`, optional voltage limits.
- `line`: from/to bus, length, either `std_type` or explicit impedance/current parameters, optional thermal limit.
- `transformer`: two-winding transformer parameters and optional thermal limit.
- `load`: active/reactive demand.
- `generator`: PQ static generator or PV voltage-controlled generator.
- `grid_connection`: external grid/slack connection.
- `settings`: global voltage limits, thermal limit, and `runpp` options.

Calculations and checks:

- Runs `pandapower.runpp`.
- Detects voltage limit violations.
- Detects line loading violations.
- Detects transformer loading violations.
- Classifies failures as:
  - `missing_parameter`
  - `missing_dependency`
  - `input_error`
  - `island_network`
  - `power_flow_not_converged`
  - `runtime_error`

Fixed evidence outputs:

- `grid_result.json`
- `violations.json`
- `grid_summary.md`
- `calculation_log.md`

These files are always written, including failure cases, so downstream evidence packaging can collect a stable artifact set.

## Setup

The local workspace was validated with Python 3.12 and pandapower 3.4.0.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run Demo

```powershell
.\.venv\Scripts\python.exe scripts\run_grid_assessment.py --input examples\demo_grid.json --output-dir outputs\demo_grid
```

The demo network has 8 buses, 6 lines, 1 transformer, 5 loads, 1 generator, and 1 external grid. It is intentionally stressed so the acceptance run detects both line overload and undervoltage.

## Run Acceptance

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
```

Acceptance cases:

- `demo_grid`: successful load flow with line overload and voltage violation.
- `missing_parameter`: required field omitted.
- `input_error`: element references an unknown bus.
- `island_network`: unsupplied bus island.
- `non_convergent`: valid network with zero allowed iterations, forcing `runpp` non-convergence classification.
- `missing_dependency`: dependency failure path with fixed artifacts.

## Readiness Check

```powershell
.\.venv\Scripts\python.exe scripts\readiness_check.py
```

The readiness check verifies required files, JSON schema readability, runner import without pandapower side effects, and the installed pandapower version.

## Evidence Rules

Public artifacts use relative paths and `source_id`; they must not contain local absolute paths such as drive-letter paths. The acceptance runner scans every emitted artifact for local path leakage.

The fixed public artifact set is:

- `grid_result.json`: run manifest and classification.
- `violations.json`: machine-readable violations.
- `grid_summary.md`: human-readable summary.
- `calculation_log.md`: calculation steps without local absolute paths.

## Input Notes

Voltage level is represented by `bus[].vn_kv`. Thermal checks use per-element `max_loading_percent` when present; otherwise they use `settings.thermal_limit_percent`.

Lines can be defined from a pandapower `std_type` or by explicit parameters:

```json
{
  "id": "L1",
  "from_bus": "B1",
  "to_bus": "B2",
  "length_km": 1.0,
  "r_ohm_per_km": 0.65,
  "x_ohm_per_km": 0.1,
  "c_nf_per_km": 210.0,
  "max_i_ka": 0.08,
  "max_loading_percent": 100.0
}
```

Generators support:

- `mode: "pq"`: creates a pandapower `sgen`.
- `mode: "pv"`: creates a pandapower `gen`.

## Release Gate

This baseline can enter the Trinity main line only when these commands pass:

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
.\.venv\Scripts\python.exe scripts\readiness_check.py
```

The missing dependency path must also work with a Python environment that does not have pandapower installed.

## License

This project is released under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
