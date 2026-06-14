---
name: ai-pandapower-skill
description: 用于电网 JSON 输入校验、pandapower 潮流计算、输入/收敛/孤岛失败分类、电压与热稳定越限识别、证据文件导出的脚本优先技能。 Use when Codex needs a script-first pandapower workflow for grid JSON validation, load-flow calculation, failure classification, voltage/thermal violation detection, and auditable evidence artifact export.
---

## Purpose / 用途

当智能体需要通过脚本优先工作流控制 pandapower，并生成可审计证据文件时，使用本技能。

Use this skill when an agent needs to control pandapower through a script-first workflow and produce auditable evidence files.

这是面向 Trinity 证据接入的 Skill-first 基线。发布关口是证据可靠性，而不是 pandapower 功能覆盖广度。

This is a Skill-first baseline for Trinity evidence intake. The release gate is evidence reliability, not broad pandapower feature coverage.

本项目采用 GNU Affero General Public License v3.0 发布，详见 `LICENSE`。

This project is released under the GNU Affero General Public License v3.0. See `LICENSE`.

## Workflow / 工作流

1. 准备电网输入 JSON，包含以下顶层字段。 Prepare a grid input JSON with these top-level sections:
   - `bus`
   - `line`
   - `transformer`
   - `load`
   - `generator`
   - `grid_connection`
   - optional `settings`
2. 运行评估脚本。 Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_grid_assessment.py --input examples\demo_grid.json --output-dir outputs\demo_grid
```

3. 检查输出目录中的四个证据文件。 Inspect the four evidence files in the output directory:
   - `grid_result.json`
   - `violations.json`
   - `grid_summary.md`
   - `calculation_log.md`

4. 执行回归验收。 For regression acceptance, run:

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
```

5. 执行发布就绪检查。 For release readiness, run:

```powershell
.\.venv\Scripts\python.exe scripts\readiness_check.py
```

## Failure Classification / 失败分类

- `missing_parameter`: 缺少必需段或字段 / required section or field is absent.
- `missing_dependency`: pandapower 或导入依赖不可用，仍写入固定失败证据 / pandapower or an import dependency is unavailable; fixed failure artifacts are still written.
- `input_error`: JSON 结构、数值类型、重复 id、非法取值或未知母线引用无效 / JSON shape, numeric type, duplicate id, invalid value, or unknown bus reference is invalid.
- `island_network`: 一个或多个母线未连接到任何投运的 `grid_connection` / one or more buses are not connected to any in-service `grid_connection`.
- `power_flow_not_converged`: 输入和拓扑检查有效后，pandapower `runpp` 未收敛 / pandapower `runpp` fails to converge after valid input and topology checks.
- `runtime_error`: 未预期运行时失败，仍写入证据文件 / unexpected runtime failure; artifacts are still written.

## Evidence Contract / 证据契约

每次运行必须写入同样的四个文件。下游工具应将 `grid_result.json` 视为运行清单，将 `violations.json` 视为机器可读越限清单。

Every run must write the same four files. Downstream tools should treat `grid_result.json` as the manifest and `violations.json` as the machine-readable violation list.

公开证据文件必须使用相对路径或 `source_id`；不得向 `grid_result.json`、`violations.json`、`grid_summary.md` 或 `calculation_log.md` 写入本机绝对路径。

Public artifacts must use relative paths or `source_id`; do not write local absolute paths into `grid_result.json`, `violations.json`, `grid_summary.md`, or `calculation_log.md`.

JSON 契约见以下文件。 The JSON contracts are documented in:

- `schemas/input_schema.json`
- `schemas/output_schema.json`

## Baseline Scope / 基线范围

基线范围包括 / The baseline scope is:

- 电网 JSON 输入校验 / grid JSON input validation
- pandapower 依赖就绪性检查 / pandapower dependency readiness
- `runpp` 潮流计算 / `runpp` load flow
- 电压和热稳定越限识别 / voltage and thermal violation detection
- 固定证据文件导出 / fixed artifact export
- 成功、错误输入、缺失依赖、孤岛和不收敛路径的验收覆盖 / acceptance coverage for success, bad input, missing dependency, island, and non-convergence paths

本基线范围外：短路计算、保护定值、动态稳定、复杂 N-1、GIS 导入、Dify 集成、GUI 操作和 Trinity 主仓库工具改动。

Out of scope for this baseline: short circuit, protection settings, dynamic stability, complex N-1, GIS import, Dify integration, GUI operation, and Trinity main repository tool changes.

## Release Gate / 发布关口

以下两个命令均通过后，才具备发布就绪性。 A release is not ready unless both commands pass:

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
.\.venv\Scripts\python.exe scripts\readiness_check.py
```

## Extension Rules / 扩展规则

不要绕过现有校验和证据导出路径。后续短路、保护定值、动态稳定、N-1 和 GIS 导入等模块，应围绕同一稳定输入/输出契约作为适配器扩展，除非显式版本化新契约。

Do not bypass the existing validation and artifact export path. Add future modules, such as short circuit, protection settings, dynamic stability, N-1, and GIS import, as adapters around the same stable input/output contract unless a new contract is explicitly versioned.
