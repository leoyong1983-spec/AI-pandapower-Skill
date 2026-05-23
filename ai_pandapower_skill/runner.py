from __future__ import annotations

import argparse
import json
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pandapower as pp
from pandapower.auxiliary import LoadflowNotConverged


SCHEMA_VERSION = "0.1.0"
SUCCESS = "success"
INPUT_ERROR = "input_error"
MISSING_PARAMETER = "missing_parameter"
ISLAND_NETWORK = "island_network"
POWER_FLOW_NOT_CONVERGED = "power_flow_not_converged"
RUNTIME_ERROR = "runtime_error"


class GridAssessmentError(Exception):
    classification = RUNTIME_ERROR

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class MissingParameterError(GridAssessmentError):
    classification = MISSING_PARAMETER


class InputDataError(GridAssessmentError):
    classification = INPUT_ERROR


class IslandNetworkError(GridAssessmentError):
    classification = ISLAND_NETWORK


class PowerFlowNotConvergedError(GridAssessmentError):
    classification = POWER_FLOW_NOT_CONVERGED


def assess_grid(input_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Run validation, pandapower load flow, violation checks, and artifact export."""
    started = time.perf_counter()
    input_path = Path(input_path)
    if output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("outputs") / f"{input_path.stem}_{stamp}"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log: list[str] = []
    artifacts = _artifact_paths(output_dir)
    data: dict[str, Any] | None = None
    net = None
    violations = _empty_violations()

    try:
        log.append(f"Started: {_utc_now()}")
        log.append(f"Input file: {input_path.resolve()}")
        data = _load_json(input_path)
        settings = _settings(data)
        log.append("Input JSON parsed.")

        net, id_maps = _build_network(data, log)
        _check_islands(data, id_maps, log)

        runpp_meta = _run_power_flow(net, settings, log)
        violations = _collect_violations(net, id_maps, settings)
        result = _success_result(input_path, output_dir, net, runpp_meta, violations, started)
        log.append("Classification: success")
    except GridAssessmentError as exc:
        result = _failure_result(input_path, output_dir, exc, started, data, net)
        log.append(f"Classification: {exc.classification}")
        log.append(f"Failure: {exc}")
        if exc.details:
            log.append(f"Failure details: {json.dumps(_to_builtin(exc.details), ensure_ascii=False)}")
    except Exception as exc:  # Defensive guard so evidence artifacts are still emitted.
        wrapped = GridAssessmentError(str(exc), {"exception_type": type(exc).__name__})
        result = _failure_result(input_path, output_dir, wrapped, started, data, net)
        log.append(f"Classification: {wrapped.classification}")
        log.append(f"Unexpected failure: {type(exc).__name__}: {exc}")

    _write_json(artifacts["grid_result.json"], result)
    _write_json(artifacts["violations.json"], violations)
    artifacts["grid_summary.md"].write_text(_render_summary(result, violations), encoding="utf-8")
    artifacts["calculation_log.md"].write_text(_render_log(log, result, artifacts), encoding="utf-8")
    return result


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise InputDataError("Input file does not exist.", {"path": str(path)})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputDataError("Input file is not valid JSON.", {"line": exc.lineno, "column": exc.colno}) from exc
    if not isinstance(payload, dict):
        raise InputDataError("Top-level input must be a JSON object.")
    return payload


def _settings(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("settings", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise InputDataError("settings must be an object.")
    voltage = raw.get("voltage_limits_pu", {}) or {}
    runpp = raw.get("runpp", {}) or {}
    return {
        "sn_mva": _float(raw.get("sn_mva", 100.0), "settings.sn_mva"),
        "frequency_hz": _float(raw.get("frequency_hz", 50.0), "settings.frequency_hz"),
        "voltage_min_pu": _float(voltage.get("min", 0.95), "settings.voltage_limits_pu.min"),
        "voltage_max_pu": _float(voltage.get("max", 1.05), "settings.voltage_limits_pu.max"),
        "thermal_limit_percent": _float(raw.get("thermal_limit_percent", 100.0), "settings.thermal_limit_percent"),
        "runpp": {
            "algorithm": str(runpp.get("algorithm", "nr")),
            "max_iteration": int(runpp.get("max_iteration", 30)),
            "init": str(runpp.get("init", "auto")),
            "enforce_q_lims": bool(runpp.get("enforce_q_lims", False)),
            "numba": bool(runpp.get("numba", False)),
        },
    }


def _build_network(data: dict[str, Any], log: list[str]) -> tuple[Any, dict[str, Any]]:
    settings = _settings(data)
    buses = _section(data, "bus", required=True)
    lines = _section(data, "line", required=False)
    trafos = _section(data, "transformer", required=False)
    loads = _section(data, "load", required=False)
    generators = _section(data, "generator", required=False)
    grids = _section(data, "grid_connection", required=True)
    if not grids:
        raise MissingParameterError("At least one grid_connection entry is required.")

    net = pp.create_empty_network(sn_mva=settings["sn_mva"], f_hz=settings["frequency_hz"])
    id_maps: dict[str, Any] = {
        "bus": {},
        "line": {},
        "transformer": {},
        "load": {},
        "generator": {},
        "grid_connection": {},
        "bus_id_by_index": {},
        "line_id_by_index": {},
        "transformer_id_by_index": {},
    }

    for item in buses:
        item_id = _id(item, "bus")
        _ensure_new(id_maps["bus"], item_id, "bus")
        vn_kv = _required_float(item, "vn_kv", f"bus[{item_id}]")
        idx = pp.create_bus(
            net,
            vn_kv=vn_kv,
            name=item.get("name", item_id),
            min_vm_pu=_optional_float(item.get("min_vm_pu"), f"bus[{item_id}].min_vm_pu"),
            max_vm_pu=_optional_float(item.get("max_vm_pu"), f"bus[{item_id}].max_vm_pu"),
            in_service=bool(item.get("in_service", True)),
        )
        id_maps["bus"][item_id] = idx
        id_maps["bus_id_by_index"][idx] = item_id

    for item in grids:
        item_id = _id(item, "grid_connection")
        _ensure_new(id_maps["grid_connection"], item_id, "grid_connection")
        bus = _bus_ref(item, "bus", id_maps)
        idx = pp.create_ext_grid(
            net,
            bus=bus,
            vm_pu=_required_float(item, "vm_pu", f"grid_connection[{item_id}]"),
            va_degree=_float(item.get("va_degree", 0.0), f"grid_connection[{item_id}].va_degree"),
            name=item.get("name", item_id),
            in_service=bool(item.get("in_service", True)),
        )
        id_maps["grid_connection"][item_id] = idx

    for item in trafos:
        item_id = _id(item, "transformer")
        _ensure_new(id_maps["transformer"], item_id, "transformer")
        idx = pp.create_transformer_from_parameters(
            net,
            hv_bus=_bus_ref(item, "hv_bus", id_maps),
            lv_bus=_bus_ref(item, "lv_bus", id_maps),
            sn_mva=_required_float(item, "sn_mva", f"transformer[{item_id}]"),
            vn_hv_kv=_required_float(item, "vn_hv_kv", f"transformer[{item_id}]"),
            vn_lv_kv=_required_float(item, "vn_lv_kv", f"transformer[{item_id}]"),
            vk_percent=_required_float(item, "vk_percent", f"transformer[{item_id}]"),
            vkr_percent=_required_float(item, "vkr_percent", f"transformer[{item_id}]"),
            pfe_kw=_required_float(item, "pfe_kw", f"transformer[{item_id}]"),
            i0_percent=_required_float(item, "i0_percent", f"transformer[{item_id}]"),
            shift_degree=_float(item.get("shift_degree", 0.0), f"transformer[{item_id}].shift_degree"),
            name=item.get("name", item_id),
            in_service=bool(item.get("in_service", True)),
        )
        if "max_loading_percent" in item:
            net.trafo.at[idx, "max_loading_percent"] = _required_float(item, "max_loading_percent", f"transformer[{item_id}]")
        id_maps["transformer"][item_id] = idx
        id_maps["transformer_id_by_index"][idx] = item_id

    for item in lines:
        item_id = _id(item, "line")
        _ensure_new(id_maps["line"], item_id, "line")
        from_bus = _bus_ref(item, "from_bus", id_maps)
        to_bus = _bus_ref(item, "to_bus", id_maps)
        if from_bus == to_bus:
            raise InputDataError("Line endpoints must refer to different buses.", {"line": item_id})
        length_km = _required_float(item, "length_km", f"line[{item_id}]")
        if length_km <= 0:
            raise InputDataError("Line length_km must be positive.", {"line": item_id, "length_km": length_km})
        if "std_type" in item:
            idx = pp.create_line(
                net,
                from_bus=from_bus,
                to_bus=to_bus,
                length_km=length_km,
                std_type=str(item["std_type"]),
                name=item.get("name", item_id),
                in_service=bool(item.get("in_service", True)),
            )
        else:
            idx = pp.create_line_from_parameters(
                net,
                from_bus=from_bus,
                to_bus=to_bus,
                length_km=length_km,
                r_ohm_per_km=_required_float(item, "r_ohm_per_km", f"line[{item_id}]"),
                x_ohm_per_km=_required_float(item, "x_ohm_per_km", f"line[{item_id}]"),
                c_nf_per_km=_required_float(item, "c_nf_per_km", f"line[{item_id}]"),
                max_i_ka=_required_float(item, "max_i_ka", f"line[{item_id}]"),
                g_us_per_km=_float(item.get("g_us_per_km", 0.0), f"line[{item_id}].g_us_per_km"),
                name=item.get("name", item_id),
                in_service=bool(item.get("in_service", True)),
            )
        if "max_loading_percent" in item:
            net.line.at[idx, "max_loading_percent"] = _required_float(item, "max_loading_percent", f"line[{item_id}]")
        id_maps["line"][item_id] = idx
        id_maps["line_id_by_index"][idx] = item_id

    for item in loads:
        item_id = _id(item, "load")
        _ensure_new(id_maps["load"], item_id, "load")
        idx = pp.create_load(
            net,
            bus=_bus_ref(item, "bus", id_maps),
            p_mw=_required_float(item, "p_mw", f"load[{item_id}]"),
            q_mvar=_float(item.get("q_mvar", 0.0), f"load[{item_id}].q_mvar"),
            name=item.get("name", item_id),
            in_service=bool(item.get("in_service", True)),
        )
        id_maps["load"][item_id] = idx

    for item in generators:
        item_id = _id(item, "generator")
        _ensure_new(id_maps["generator"], item_id, "generator")
        bus = _bus_ref(item, "bus", id_maps)
        mode = str(item.get("mode", "pq")).lower()
        if mode == "pv":
            idx = pp.create_gen(
                net,
                bus=bus,
                p_mw=_required_float(item, "p_mw", f"generator[{item_id}]"),
                vm_pu=_float(item.get("vm_pu", 1.0), f"generator[{item_id}].vm_pu"),
                name=item.get("name", item_id),
                in_service=bool(item.get("in_service", True)),
            )
            for column in ("min_q_mvar", "max_q_mvar", "min_p_mw", "max_p_mw"):
                if column in item:
                    net.gen.at[idx, column] = _required_float(item, column, f"generator[{item_id}]")
        elif mode == "pq":
            idx = pp.create_sgen(
                net,
                bus=bus,
                p_mw=_required_float(item, "p_mw", f"generator[{item_id}]"),
                q_mvar=_float(item.get("q_mvar", 0.0), f"generator[{item_id}].q_mvar"),
                name=item.get("name", item_id),
                in_service=bool(item.get("in_service", True)),
            )
        else:
            raise InputDataError("generator.mode must be either 'pq' or 'pv'.", {"generator": item_id, "mode": mode})
        id_maps["generator"][item_id] = idx

    log.append(
        "Pandapower network built: "
        f"{len(net.bus)} bus, {len(net.line)} line, {len(net.trafo)} transformer, "
        f"{len(net.load)} load, {len(net.gen) + len(net.sgen)} generator."
    )
    return net, id_maps


def _check_islands(data: dict[str, Any], id_maps: dict[str, Any], log: list[str]) -> None:
    bus_ids = set(id_maps["bus"].keys())
    if not bus_ids:
        raise MissingParameterError("At least one bus entry is required.")

    adjacency: dict[str, set[str]] = {bus_id: set() for bus_id in bus_ids}
    for line in data.get("line", []) or []:
        if not bool(line.get("in_service", True)):
            continue
        a = str(line["from_bus"])
        b = str(line["to_bus"])
        adjacency[a].add(b)
        adjacency[b].add(a)
    for trafo in data.get("transformer", []) or []:
        if not bool(trafo.get("in_service", True)):
            continue
        a = str(trafo["hv_bus"])
        b = str(trafo["lv_bus"])
        adjacency[a].add(b)
        adjacency[b].add(a)

    source_ids = [str(grid["bus"]) for grid in data.get("grid_connection", []) or [] if bool(grid.get("in_service", True))]
    if not source_ids:
        raise MissingParameterError("At least one in-service grid_connection is required.")

    seen: set[str] = set()
    queue: deque[str] = deque(source_ids)
    while queue:
        bus = queue.popleft()
        if bus in seen:
            continue
        seen.add(bus)
        queue.extend(sorted(adjacency.get(bus, set()) - seen))

    unsupplied = sorted(bus_ids - seen)
    if unsupplied:
        raise IslandNetworkError(
            "Network contains bus islands not connected to any grid_connection.",
            {"unsupplied_buses": unsupplied, "source_buses": source_ids},
        )
    log.append("Island check passed: all buses are connected to an in-service grid_connection.")


def _run_power_flow(net: Any, settings: dict[str, Any], log: list[str]) -> dict[str, Any]:
    options = settings["runpp"]
    started = time.perf_counter()
    try:
        pp.runpp(
            net,
            algorithm=options["algorithm"],
            max_iteration=options["max_iteration"],
            init=options["init"],
            enforce_q_lims=options["enforce_q_lims"],
            numba=options["numba"],
        )
    except LoadflowNotConverged as exc:
        raise PowerFlowNotConvergedError(
            "pandapower runpp did not converge.",
            {"algorithm": options["algorithm"], "max_iteration": options["max_iteration"], "message": str(exc)},
        ) from exc
    elapsed = time.perf_counter() - started
    converged = bool(getattr(net, "converged", False))
    if not converged:
        raise PowerFlowNotConvergedError(
            "pandapower runpp finished without a converged flag.",
            {"algorithm": options["algorithm"], "max_iteration": options["max_iteration"]},
        )
    log.append(f"runpp converged in {elapsed:.4f} s.")
    return {
        "converged": True,
        "algorithm": options["algorithm"],
        "max_iteration": options["max_iteration"],
        "elapsed_s": round(elapsed, 6),
    }


def _collect_violations(net: Any, id_maps: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    violations = _empty_violations()

    for idx, row in net.res_bus.iterrows():
        bus_id = id_maps["bus_id_by_index"].get(idx, str(idx))
        vm_pu = _clean_float(row.get("vm_pu"))
        min_limit = _clean_float(net.bus.at[idx, "min_vm_pu"]) if "min_vm_pu" in net.bus.columns else None
        max_limit = _clean_float(net.bus.at[idx, "max_vm_pu"]) if "max_vm_pu" in net.bus.columns else None
        if min_limit is None:
            min_limit = settings["voltage_min_pu"]
        if max_limit is None:
            max_limit = settings["voltage_max_pu"]
        if vm_pu is None:
            continue
        if vm_pu < min_limit or vm_pu > max_limit:
            violations["voltage"].append(
                {
                    "bus_id": bus_id,
                    "bus_index": int(idx),
                    "vm_pu": round(vm_pu, 6),
                    "limit_min_pu": min_limit,
                    "limit_max_pu": max_limit,
                    "violation": "undervoltage" if vm_pu < min_limit else "overvoltage",
                    "margin_pu": round(vm_pu - min_limit if vm_pu < min_limit else vm_pu - max_limit, 6),
                }
            )

    for idx, row in net.res_line.iterrows():
        line_id = id_maps["line_id_by_index"].get(idx, str(idx))
        loading = _clean_float(row.get("loading_percent"))
        limit = _element_limit(net.line, idx, settings["thermal_limit_percent"])
        if loading is None:
            continue
        if loading > limit:
            from_idx = int(net.line.at[idx, "from_bus"])
            to_idx = int(net.line.at[idx, "to_bus"])
            violations["line_loading"].append(
                {
                    "line_id": line_id,
                    "line_index": int(idx),
                    "from_bus": id_maps["bus_id_by_index"].get(from_idx, str(from_idx)),
                    "to_bus": id_maps["bus_id_by_index"].get(to_idx, str(to_idx)),
                    "loading_percent": round(loading, 6),
                    "limit_percent": limit,
                    "excess_percent": round(loading - limit, 6),
                }
            )

    for idx, row in net.res_trafo.iterrows():
        trafo_id = id_maps["transformer_id_by_index"].get(idx, str(idx))
        loading = _clean_float(row.get("loading_percent"))
        limit = _element_limit(net.trafo, idx, settings["thermal_limit_percent"])
        if loading is None:
            continue
        if loading > limit:
            hv_idx = int(net.trafo.at[idx, "hv_bus"])
            lv_idx = int(net.trafo.at[idx, "lv_bus"])
            violations["transformer_loading"].append(
                {
                    "transformer_id": trafo_id,
                    "transformer_index": int(idx),
                    "hv_bus": id_maps["bus_id_by_index"].get(hv_idx, str(hv_idx)),
                    "lv_bus": id_maps["bus_id_by_index"].get(lv_idx, str(lv_idx)),
                    "loading_percent": round(loading, 6),
                    "limit_percent": limit,
                    "excess_percent": round(loading - limit, 6),
                }
            )

    violations["counts"] = {
        "voltage": len(violations["voltage"]),
        "line_loading": len(violations["line_loading"]),
        "transformer_loading": len(violations["transformer_loading"]),
        "total": len(violations["voltage"]) + len(violations["line_loading"]) + len(violations["transformer_loading"]),
    }
    violations["status"] = "violations_found" if violations["counts"]["total"] else "no_violations"
    return violations


def _success_result(
    input_path: Path,
    output_dir: Path,
    net: Any,
    runpp_meta: dict[str, Any],
    violations: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "classification": SUCCESS,
        "created_at_utc": _utc_now(),
        "input_file": str(input_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "pandapower_version": pp.__version__,
        "network": {
            "bus_count": int(len(net.bus)),
            "line_count": int(len(net.line)),
            "transformer_count": int(len(net.trafo)),
            "load_count": int(len(net.load)),
            "generator_count": int(len(net.gen) + len(net.sgen)),
            "grid_connection_count": int(len(net.ext_grid)),
        },
        "runpp": runpp_meta,
        "summary": {
            "voltage_violation_count": violations["counts"]["voltage"],
            "line_overload_count": violations["counts"]["line_loading"],
            "transformer_overload_count": violations["counts"]["transformer_loading"],
            "total_violation_count": violations["counts"]["total"],
            "min_vm_pu": _series_min(net.res_bus.get("vm_pu")),
            "max_vm_pu": _series_max(net.res_bus.get("vm_pu")),
            "max_line_loading_percent": _series_max(net.res_line.get("loading_percent")),
            "max_transformer_loading_percent": _series_max(net.res_trafo.get("loading_percent")),
        },
        "artifacts": _artifact_manifest(output_dir),
        "elapsed_s": round(time.perf_counter() - started, 6),
    }


def _failure_result(
    input_path: Path,
    output_dir: Path,
    exc: GridAssessmentError,
    started: float,
    data: dict[str, Any] | None,
    net: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "classification": exc.classification,
        "created_at_utc": _utc_now(),
        "input_file": str(input_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "pandapower_version": pp.__version__,
        "error": {
            "message": str(exc),
            "details": _to_builtin(exc.details),
        },
        "artifacts": _artifact_manifest(output_dir),
        "elapsed_s": round(time.perf_counter() - started, 6),
    }
    if data is not None:
        result["input_sections"] = sorted(data.keys())
    if net is not None:
        result["network"] = {
            "bus_count": int(len(net.bus)),
            "line_count": int(len(net.line)),
            "transformer_count": int(len(net.trafo)),
            "load_count": int(len(net.load)),
            "generator_count": int(len(net.gen) + len(net.sgen)),
            "grid_connection_count": int(len(net.ext_grid)),
        }
    return result


def _render_summary(result: dict[str, Any], violations: dict[str, Any]) -> str:
    lines = [
        "# Grid Summary",
        "",
        f"- Status: `{result['status']}`",
        f"- Classification: `{result['classification']}`",
        f"- Input: `{result['input_file']}`",
        f"- Created UTC: `{result['created_at_utc']}`",
        f"- pandapower: `{result.get('pandapower_version', 'unknown')}`",
        "",
    ]
    if result["status"] == "success":
        network = result["network"]
        summary = result["summary"]
        lines.extend(
            [
                "## Network",
                "",
                f"- Buses: {network['bus_count']}",
                f"- Lines: {network['line_count']}",
                f"- Transformers: {network['transformer_count']}",
                f"- Loads: {network['load_count']}",
                f"- Generators: {network['generator_count']}",
                f"- Grid connections: {network['grid_connection_count']}",
                "",
                "## Run Results",
                "",
                f"- Voltage range: {summary['min_vm_pu']} to {summary['max_vm_pu']} pu",
                f"- Max line loading: {summary['max_line_loading_percent']} %",
                f"- Max transformer loading: {summary['max_transformer_loading_percent']} %",
                f"- Voltage violations: {summary['voltage_violation_count']}",
                f"- Line overloads: {summary['line_overload_count']}",
                f"- Transformer overloads: {summary['transformer_overload_count']}",
                f"- Total violations: {summary['total_violation_count']}",
                "",
            ]
        )
        lines.extend(_markdown_violation_table("Voltage Violations", violations["voltage"], ["bus_id", "vm_pu", "limit_min_pu", "limit_max_pu", "violation"]))
        lines.extend(_markdown_violation_table("Line Overloads", violations["line_loading"], ["line_id", "from_bus", "to_bus", "loading_percent", "limit_percent"]))
        lines.extend(
            _markdown_violation_table(
                "Transformer Overloads",
                violations["transformer_loading"],
                ["transformer_id", "hv_bus", "lv_bus", "loading_percent", "limit_percent"],
            )
        )
    else:
        lines.extend(
            [
                "## Failure",
                "",
                f"- Message: {result['error']['message']}",
                f"- Details: `{json.dumps(result['error'].get('details', {}), ensure_ascii=False)}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _markdown_violation_table(title: str, rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        lines.extend(["No records.", ""])
        return lines
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    lines.append("")
    return lines


def _render_log(log: list[str], result: dict[str, Any], artifacts: dict[str, Path]) -> str:
    lines = [
        "# Calculation Log",
        "",
        "## Steps",
        "",
    ]
    lines.extend(f"- {entry}" for entry in log)
    lines.extend(
        [
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Classification: `{result['classification']}`",
            f"- Elapsed seconds: `{result['elapsed_s']}`",
            "",
            "## Artifacts",
            "",
        ]
    )
    for name, path in artifacts.items():
        lines.append(f"- {name}: `{path.resolve()}`")
    return "\n".join(lines).rstrip() + "\n"


def _section(data: dict[str, Any], name: str, required: bool) -> list[dict[str, Any]]:
    if name not in data:
        if required:
            raise MissingParameterError(f"Missing required section: {name}.", {"section": name})
        return []
    section = data[name]
    if section is None:
        return []
    if not isinstance(section, list):
        raise InputDataError(f"Section {name} must be a list.", {"section": name})
    for index, item in enumerate(section):
        if not isinstance(item, dict):
            raise InputDataError(f"Section {name} item must be an object.", {"section": name, "index": index})
    return section


def _id(item: dict[str, Any], section: str) -> str:
    if "id" not in item:
        raise MissingParameterError(f"Missing id in {section} entry.", {"section": section})
    value = str(item["id"]).strip()
    if not value:
        raise InputDataError(f"Empty id in {section} entry.", {"section": section})
    return value


def _ensure_new(mapping: dict[str, Any], item_id: str, section: str) -> None:
    if item_id in mapping:
        raise InputDataError(f"Duplicate id in {section} section.", {"section": section, "id": item_id})


def _bus_ref(item: dict[str, Any], key: str, id_maps: dict[str, Any]) -> int:
    if key not in item:
        raise MissingParameterError(f"Missing bus reference field: {key}.", {"field": key})
    bus_id = str(item[key])
    if bus_id not in id_maps["bus"]:
        raise InputDataError("Element references an unknown bus.", {"field": key, "bus": bus_id})
    return int(id_maps["bus"][bus_id])


def _required_float(item: dict[str, Any], key: str, context: str) -> float:
    if key not in item:
        raise MissingParameterError(f"Missing required parameter: {context}.{key}.", {"context": context, "parameter": key})
    return _float(item[key], f"{context}.{key}")


def _float(value: Any, context: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputDataError(f"Parameter must be numeric: {context}.", {"parameter": context, "value": value}) from exc
    if not math.isfinite(result):
        raise InputDataError(f"Parameter must be finite: {context}.", {"parameter": context, "value": value})
    return result


def _optional_float(value: Any, context: str) -> float | None:
    if value is None:
        return None
    return _float(value, context)


def _clean_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or pd.isna(result):
        return None
    return result


def _element_limit(table: pd.DataFrame, idx: int, default: float) -> float:
    if "max_loading_percent" in table.columns:
        limit = _clean_float(table.at[idx, "max_loading_percent"])
        if limit is not None:
            return limit
    return default


def _series_min(series: Any) -> float | None:
    if series is None or len(series) == 0:
        return None
    value = _clean_float(series.min())
    return None if value is None else round(value, 6)


def _series_max(series: Any) -> float | None:
    if series is None or len(series) == 0:
        return None
    value = _clean_float(series.max())
    return None if value is None else round(value, 6)


def _empty_violations() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "not_evaluated",
        "counts": {"voltage": 0, "line_loading": 0, "transformer_loading": 0, "total": 0},
        "voltage": [],
        "line_loading": [],
        "transformer_loading": [],
    }


def _artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {name: output_dir / name for name in ("grid_result.json", "violations.json", "grid_summary.md", "calculation_log.md")}


def _artifact_manifest(output_dir: Path) -> dict[str, str]:
    return {name: str(path.resolve()) for name, path in _artifact_paths(output_dir).items()}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_to_builtin(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_builtin(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_builtin(v) for v in value]
    if isinstance(value, tuple):
        return [_to_builtin(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, Path):
        return str(value)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a pandapower grid assessment and export evidence artifacts.")
    parser.add_argument("--input", required=True, help="Path to grid input JSON.")
    parser.add_argument("--output-dir", required=True, help="Directory for grid_result.json, violations.json, grid_summary.md, calculation_log.md.")
    args = parser.parse_args(argv)

    result = assess_grid(args.input, args.output_dir)
    print(json.dumps({"status": result["status"], "classification": result["classification"], "output_dir": result["output_dir"]}, ensure_ascii=False))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
