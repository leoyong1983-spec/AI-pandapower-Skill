# AI pandapower Skill / AI pandapower 技能

## 中文说明

本仓库提供一个小型、可审计的 pandapower 自动化技能，用于电网 JSON 输入校验、潮流计算、越限识别和证据文件导出。

当前版本是 Trinity 集成的基线关口，重点是证据可靠性，而不是覆盖 pandapower 的全部能力。本轮基线只覆盖潮流计算和越限复核；短路计算、保护定值、动态稳定、复杂 N-1、GIS 导入和图形界面操作仍不在当前范围内。

## English Description

This repository provides a small, auditable pandapower automation skill for grid JSON validation, load-flow calculation, violation detection, and evidence export.

The current release is a baseline Trinity integration gate. The priority is reliable evidence, not broad pandapower feature coverage. This baseline intentionally covers load flow and violation review only; short circuit, protection settings, dynamic stability, complex N-1, GIS import, and GUI operation remain out of scope.

## 功能范围 / Current Capability

支持的输入段 / Supported input sections:

- `bus`: 母线编号、名称、电压等级 `vn_kv`，以及可选电压限值 / bus id, name, voltage level `vn_kv`, and optional voltage limits.
- `line`: 起止母线、长度、`std_type` 或显式阻抗/电流参数，以及可选热稳定限值 / from/to bus, length, either `std_type` or explicit impedance/current parameters, and optional thermal limit.
- `transformer`: 双绕组变压器参数和可选热稳定限值 / two-winding transformer parameters and optional thermal limit.
- `load`: 有功和无功负荷 / active and reactive demand.
- `generator`: PQ 静态发电机或 PV 电压控制发电机 / PQ static generator or PV voltage-controlled generator.
- `grid_connection`: 外部电网或平衡节点连接 / external grid or slack connection.
- `settings`: 全局电压限值、热稳定限值和 `runpp` 选项 / global voltage limits, thermal limit, and `runpp` options.

计算与检查 / Calculations and checks:

- 执行 `pandapower.runpp` / Run `pandapower.runpp`.
- 识别电压越限 / Detect voltage limit violations.
- 识别线路负载率越限 / Detect line loading violations.
- 识别变压器负载率越限 / Detect transformer loading violations.
- 对失败路径进行分类 / Classify failures as:
  - `missing_parameter`
  - `missing_dependency`
  - `input_error`
  - `island_network`
  - `power_flow_not_converged`
  - `runtime_error`

固定证据输出 / Fixed evidence outputs:

- `grid_result.json`
- `violations.json`
- `grid_summary.md`
- `calculation_log.md`

上述文件在成功和失败场景下都会生成，便于下游证据包稳定收集。 These files are always written, including failure cases, so downstream evidence packaging can collect a stable artifact set.

## 环境配置 / Setup

本地工作区已使用 Python 3.12 和 pandapower 3.4.0 验证。 The local workspace was validated with Python 3.12 and pandapower 3.4.0.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 运行示例 / Run Demo

```powershell
.\.venv\Scripts\python.exe scripts\run_grid_assessment.py --input examples\demo_grid.json --output-dir outputs\demo_grid
```

示例网络包含 8 个母线、6 条线路、1 台变压器、5 个负荷、1 台发电机和 1 个外部电网。该网络被有意设置为偏紧工况，因此验收运行会识别线路过载和低电压问题。

The demo network has 8 buses, 6 lines, 1 transformer, 5 loads, 1 generator, and 1 external grid. It is intentionally stressed so the acceptance run detects both line overload and undervoltage.

## 验收运行 / Run Acceptance

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
```

验收用例 / Acceptance cases:

- `demo_grid`: 潮流成功，并存在线路过载和电压越限 / successful load flow with line overload and voltage violation.
- `missing_parameter`: 缺少必填字段 / required field omitted.
- `input_error`: 元件引用未知母线 / element references an unknown bus.
- `island_network`: 存在无供电孤岛母线 / unsupplied bus island.
- `non_convergent`: 合法网络设置零迭代次数，强制触发 `runpp` 不收敛分类 / valid network with zero allowed iterations, forcing `runpp` non-convergence classification.
- `missing_dependency`: 缺失依赖时仍输出固定证据文件 / dependency failure path with fixed artifacts.

## 就绪检查 / Readiness Check

```powershell
.\.venv\Scripts\python.exe scripts\readiness_check.py
```

就绪检查会验证必需文件、JSON Schema 可读性、runner 导入是否避免 pandapower 副作用，以及已安装的 pandapower 版本。

The readiness check verifies required files, JSON schema readability, runner import without pandapower side effects, and the installed pandapower version.

## 证据规则 / Evidence Rules

公开证据文件必须使用相对路径和 `source_id`，不得包含盘符路径等本机绝对路径。验收脚本会扫描所有输出证据，检查是否泄漏本地路径。

Public artifacts use relative paths and `source_id`; they must not contain local absolute paths such as drive-letter paths. The acceptance runner scans every emitted artifact for local path leakage.

固定公开证据文件 / Fixed public artifact set:

- `grid_result.json`: 运行清单和失败分类 / run manifest and classification.
- `violations.json`: 机器可读越限清单 / machine-readable violations.
- `grid_summary.md`: 人类可读摘要 / human-readable summary.
- `calculation_log.md`: 不含本地绝对路径的计算步骤记录 / calculation steps without local absolute paths.

## 输入说明 / Input Notes

电压等级使用 `bus[].vn_kv` 表示。热稳定检查优先使用元件级 `max_loading_percent`；若未提供，则使用 `settings.thermal_limit_percent`。

Voltage level is represented by `bus[].vn_kv`. Thermal checks use per-element `max_loading_percent` when present; otherwise they use `settings.thermal_limit_percent`.

线路可以使用 pandapower `std_type`，也可以使用显式参数定义。 Lines can be defined from a pandapower `std_type` or by explicit parameters:

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

发电机支持 / Generators support:

- `mode: "pq"`: 创建 pandapower `sgen` / creates a pandapower `sgen`.
- `mode: "pv"`: 创建 pandapower `gen` / creates a pandapower `gen`.

## 发布关口 / Release Gate

该基线进入 Trinity 主线前，必须通过以下命令。 This baseline can enter the Trinity main line only when these commands pass:

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
.\.venv\Scripts\python.exe scripts\readiness_check.py
```

缺失依赖路径也必须在未安装 pandapower 的 Python 环境中可用。 The missing dependency path must also work with a Python environment that does not have pandapower installed.

## 许可证 / License

本项目采用 GNU Affero General Public License v3.0 发布，详见 [LICENSE](LICENSE)。 This project is released under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
