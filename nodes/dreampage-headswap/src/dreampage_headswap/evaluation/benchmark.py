"""Compare archived outputs on byte-identical inputs; never executes production."""
from __future__ import annotations

import json
import math
import platform
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from ..data.records import file_sha256, read_jsonl, resolve_asset, validate_pair_manifests
from ..data.registry import resolve_manifest_inventory
from ..masking import load_headmask

INPUT_KEYS = ("source", "template", "headmask")
RECOMMENDED_TAGS = (
    "frontal_to_frontal", "slight_three_quarter", "strong_three_quarter", "opposite_angle",
    "looking_up", "looking_down", "different_gaze", "happy", "sad", "neutral", "closed_mouth",
    "challenging_lighting", "warm_light", "cold_light", "small_face", "large_face",
    "different_hairstyle", "hair_crossing_boundary", "realistic_template", "generated_template",
    "high_resolution_template", "low_resolution_reference",
)
UNAVAILABLE_METRICS = {
    "identity_similarity": "Requires reviewed independent identity evaluator and validated child-domain calibration",
    "local_identity_similarity": "Requires validated local-identity evaluator",
    "pose_preservation": "Requires licensed calibrated geometry provider",
    "expression_preservation": "Requires licensed calibrated expression provider",
    "outside_mask_perceptual_difference": "No licensed perceptual evaluator configured; pixel metrics are available",
    "realism": "Human comparison or a validated realism evaluator required",
    "age_preservation": "Known age and a validated age-consistency evaluator required",
    "failure_rate": "Requires preregistered quality gates or adjudicated human failures",
}


def save_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def archive_baseline(workflow: str | Path, config: str | Path, destination: str | Path) -> dict:
    """Copy only explicitly supplied workflow/config, keeping checksums and no execution."""
    workflow, config, destination = Path(workflow).resolve(), Path(config).resolve(), Path(destination).resolve()
    if not workflow.is_file() or not config.is_file():
        raise ValueError("Both workflow and configuration must exist")
    destination.mkdir(parents=True, exist_ok=False)
    frozen_workflow, frozen_config = destination / ("workflow" + workflow.suffix), destination / ("config" + config.suffix)
    shutil.copy2(workflow, frozen_workflow)
    shutil.copy2(config, frozen_config)
    metadata = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                "workflow_file": frozen_workflow.name, "config_file": frozen_config.name,
                "workflow_sha256": file_sha256(frozen_workflow), "config_sha256": file_sha256(frozen_config),
                "executed": False, "notes": "Baseline configuration archive only; no image generation was run"}
    save_json(destination / "archive.json", metadata)
    return metadata


def record_stored_result(*, source, template, headmask, result, workflow, config, method_id: str,
                         destination, performance: dict | None = None, checkpoint_sha256: str | None = None,
                         sources=None, mask_channel: str = "red") -> dict:
    """Attest to a stored run. Caller must verify these WERE the actual production inputs."""
    if not isinstance(method_id, str) or not method_id.strip():
        raise ValueError("method_id required")
    references = [str(Path(path).resolve()) for path in (sources if sources is not None else [source])]
    inputs = _input_attestation(source, template, headmask, references, mask_channel)
    performance = _validate_performance(performance)
    metadata = {"schema_version": 1, "method_id": method_id,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "input_sha256": inputs,
                "result_sha256": file_sha256(result), "workflow_sha256": file_sha256(workflow),
                "config_sha256": file_sha256(config), "checkpoint_sha256": checkpoint_sha256,
                "performance": performance, "python": platform.python_version(),
                "attestation": "Operator-provided run provenance; this function does not generate or reconstruct outputs"}
    save_json(destination, metadata)
    return metadata


def _input_attestation(source, template, headmask, sources, mask_channel) -> dict:
    if mask_channel not in {"red", "green", "blue", "alpha", "luminance"}:
        raise ValueError("Invalid mask_channel")
    if not sources or len(set(sources)) != len(sources) or str(Path(source).resolve()) not in sources:
        raise ValueError("sources must include the primary source and distinct reference paths")
    from ..data.preprocessing import decoded_pixel_sha256
    if len({decoded_pixel_sha256(path) for path in sources}) != len(sources):
        raise ValueError("Multi-reference sources contain duplicate captures")
    return {**{key: file_sha256(path) for key, path in
               {"source": source, "template": template, "headmask": headmask}.items()},
            "sources": [file_sha256(path) for path in sources], "mask_channel": mask_channel}


def validate_case_assets(raw: dict, base: Path) -> tuple[dict, dict, dict, dict]:
    """Common provenance/geometry gate for numerical and blind human comparisons."""
    case = dict(raw)
    for key in (*INPUT_KEYS, "current_result", "new_result", "current_run", "new_run"):
        case[key] = str(resolve_asset(base, case.get(key)))
    sources = raw.get("sources", [raw["source"]])
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    case["sources"] = [str(resolve_asset(base, source)) for source in sources]
    case["mask_channel"] = raw.get("mask_channel", "red")
    if case.get("ground_truth"):
        case["ground_truth"] = str(resolve_asset(base, case["ground_truth"]))
    inputs = _input_attestation(case["source"], case["template"], case["headmask"], case["sources"], case["mask_channel"])
    current = _run_record(Path(case["current_run"]), inputs, Path(case["current_result"]))
    new = _run_record(Path(case["new_run"]), inputs, Path(case["new_result"]))
    template = _load_rgb(case["template"])
    for key in ("current_result", "new_result", "ground_truth"):
        if case.get(key) and _load_rgb(case[key]).shape != template.shape:
            raise ValueError("Result/template/headmask dimensions must match exactly; no implicit benchmark resizing")
    if load_headmask(case["headmask"], channel=case["mask_channel"]).values.shape != template.shape[:2]:
        raise ValueError("Result/template/headmask dimensions must match exactly")
    return case, inputs, current, new


def _validate_performance(value: dict | None) -> dict:
    if value is None:
        return {"latency_ms": None, "peak_vram_bytes": None, "measurement_protocol": None}
    if not isinstance(value, dict):
        raise ValueError("performance must be an object")
    output = {"latency_ms": value.get("latency_ms"), "peak_vram_bytes": value.get("peak_vram_bytes"),
              "measurement_protocol": value.get("measurement_protocol"), "hardware": value.get("hardware"),
              "device": value.get("device"), "warmup_runs": value.get("warmup_runs")}
    for key in ("latency_ms", "peak_vram_bytes"):
        number = output[key]
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float))
                                   or not math.isfinite(number) or number < 0):
            raise ValueError(f"Invalid measured {key}")
    if output["peak_vram_bytes"] is not None and int(output["peak_vram_bytes"]) != output["peak_vram_bytes"]:
        raise ValueError("peak_vram_bytes must be an integer byte count")
    if output["warmup_runs"] is not None and (not isinstance(output["warmup_runs"], int)
                                              or isinstance(output["warmup_runs"], bool) or output["warmup_runs"] < 0):
        raise ValueError("warmup_runs must be a nonnegative integer")
    if any(output[key] is not None for key in ("latency_ms", "peak_vram_bytes")):
        if any(not isinstance(output[key], str) or not output[key].strip() for key in ("measurement_protocol", "hardware")):
            raise ValueError("Performance numbers require actual measurement protocol and hardware metadata")
    return output


def _load_rgb(path) -> np.ndarray:
    with Image.open(path) as image:
        if image.mode.startswith("I") or image.mode == "F":
            raise ValueError("Benchmark requires explicit conversion of high-bit-depth images; silently truncating precision is forbidden")
        if image.getexif().get(274, 1) != 1:
            raise ValueError("Canonical image orientation is required for pixel comparison")
        return np.asarray(image.convert("RGB")).copy()


def _run_record(path: Path, inputs: dict, result: Path) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("input_sha256") != inputs:
        raise ValueError(f"Input provenance mismatch in {path}")
    if record.get("result_sha256") != file_sha256(result):
        raise ValueError(f"Stored result has changed since run record: {result}")
    for key in ("workflow_sha256", "config_sha256"):
        digest = record.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Run record missing valid {key}: {path}")
    if not record.get("method_id"):
        raise ValueError("Run record must name an organizer-visible method_id")
    record["performance"] = _validate_performance(record.get("performance"))
    return record


def _measure(template: np.ndarray, output: np.ndarray, mask: np.ndarray,
             target: np.ndarray | None) -> dict:
    from .metrics import preservation_metrics
    if output.shape != template.shape or mask.shape != template.shape[:2]:
        raise ValueError("Result/template/headmask dimensions must match exactly")
    result = dict(preservation_metrics(template, output, mask))
    original = template.astype(np.float32) / 255.0
    generated = output.astype(np.float32) / 255.0
    editable = mask > 0
    # This measures departure from the original at its inside edge, NOT perceived seamlessness.
    interior = editable.copy()
    interior[1:, :] &= editable[:-1, :]
    interior[:-1, :] &= editable[1:, :]
    interior[:, 1:] &= editable[:, :-1]
    interior[:, :-1] &= editable[:, 1:]
    boundary = editable & ~interior
    result["boundary_template_mae"] = float(np.abs(generated - original)[boundary].mean()) if boundary.any() else None
    if target is not None:
        if target.shape != template.shape:
            raise ValueError("Ground truth dimensions must match template")
        target_float = target.astype(np.float32) / 255.0
        result["masked_reconstruction_mae"] = float(np.abs(generated - target_float)[editable].mean()) if editable.any() else None
        mse = float(np.square(generated - target_float)[editable].mean()) if editable.any() else None
        result["masked_reconstruction_psnr_db"] = -10.0 * math.log10(mse) if mse and mse > 0 else None
        result["masked_reconstruction_exact"] = bool(mse == 0) if mse is not None else None
    else:
        result.update(masked_reconstruction_mae=None, masked_reconstruction_psnr_db=None, masked_reconstruction_exact=None)
    result.update({name: None for name in UNAVAILABLE_METRICS})
    return result


def visual_grid(case: dict, output_path: str | Path, *, cell_size: int = 256) -> None:
    columns = [("Reference", case["source"]), ("Template", case["template"]),
               ("Current system", case["current_result"]), ("New model", case["new_result"])]
    if case.get("ground_truth"):
        columns.append(("Ground truth", case["ground_truth"]))
    grid = Image.new("RGB", (cell_size * len(columns), cell_size + 48), "#202226")
    draw = ImageDraw.Draw(grid)
    for index, (label, path) in enumerate(columns):
        with Image.open(path) as image:
            tile = ImageOps.contain(image.convert("RGB"), (cell_size - 12, cell_size - 12))
        x, y = index * cell_size + (cell_size - tile.width) // 2, 26 + (cell_size - tile.height) // 2
        grid.paste(tile, (x, y))
        draw.text((index * cell_size + 8, 8), label, fill="white")
    if case.get("synthetic"):
        draw.text((8, cell_size + 31), "SYNTHETIC FIXTURE - NOT A QUALITY BENCHMARK", fill="#ffb366")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(output_path)


def benchmark(manifest: str | Path, output_dir: str | Path, *, training_manifests=(),
              allow_synthetic: bool = False, registry_path=None) -> dict:
    manifest, output_dir = Path(manifest).resolve(), Path(output_dir).resolve()
    raw_cases = read_jsonl(manifest)
    if not raw_cases:
        raise ValueError("Benchmark manifest is empty")
    training_manifests, split_audit = resolve_manifest_inventory(training_manifests, registry_path=registry_path,
        require_registry=any(case.get("synthetic") is not True for case in raw_cases))
    training_rows = validate_pair_manifests(training_manifests, allow_synthetic=allow_synthetic, registry_path=registry_path) if training_manifests else []
    training_ids = {row["identity_id"] for row in training_rows if row["split"] in {"train", "validation"}}
    from ..data.preprocessing import decoded_pixel_sha256
    training_hashes = {decoded_pixel_sha256(path) for row in training_rows if row["split"] in {"train", "validation"}
                       for path in row["sources"] + [row["template"], row["ground_truth"]]}
    cases, seen, tags = [], set(), Counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    for raw in raw_cases:
        case = dict(raw)
        case_id, identity_id = case.get("case_id"), case.get("identity_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in case_id):
            raise ValueError("case_id must be unique and contain only letters, digits, underscore or hyphen")
        seen.add(case_id)
        if not isinstance(identity_id, str) or not identity_id or case.get("split") not in {"test", "benchmark"}:
            raise ValueError("Benchmark cases require identity_id and test/benchmark split")
        if identity_id in training_ids:
            raise ValueError(f"Benchmark identity leaks into training/validation: {identity_id}")
        if not isinstance(case.get("synthetic", False), bool):
            raise ValueError("synthetic must be boolean")
        if case.get("synthetic") and not allow_synthetic:
            raise ValueError("Synthetic fixtures are not a quality benchmark; explicit opt-in required")
        case_tags = case.get("tags", [])
        if not isinstance(case_tags, list) or not case_tags or not all(isinstance(tag, str) and tag for tag in case_tags):
            raise ValueError("Every benchmark case requires coverage tags")
        tags.update(set(case_tags))
        case, inputs, current, new = validate_case_assets(case, manifest.parent)
        comparison_inputs = case["sources"] + [case["template"]] + ([case["ground_truth"]] if case.get("ground_truth") else [])
        if any(decoded_pixel_sha256(path) in training_hashes for path in comparison_inputs):
            raise ValueError("Benchmark image content overlaps training/validation data")
        template, mask = _load_rgb(case["template"]), load_headmask(case["headmask"], channel=case["mask_channel"]).values
        target = _load_rgb(case["ground_truth"]) if case.get("ground_truth") else None
        current_metrics = _measure(template, _load_rgb(case["current_result"]), mask, target)
        new_metrics = _measure(template, _load_rgb(case["new_result"]), mask, target)
        deltas = {key: float(new_metrics[key] - value) if isinstance(value, (int, float)) and not isinstance(value, bool)
                  and isinstance(new_metrics.get(key), (int, float)) and not isinstance(new_metrics[key], bool) else None
                  for key, value in current_metrics.items()}
        performance_deltas = {}
        comparable_performance = all(current["performance"].get(key) == new["performance"].get(key)
                                     and current["performance"].get(key) is not None
                                     for key in ("hardware", "measurement_protocol", "device", "warmup_runs"))
        for key in ("latency_ms", "peak_vram_bytes"):
            before, after = current["performance"].get(key), new["performance"].get(key)
            performance_deltas[key] = after - before if comparable_performance and before is not None and after is not None else None
        grid_path = output_dir / "grids" / f"{case_id}.png"
        visual_grid(case, grid_path)
        cases.append({"case_id": case_id, "identity_id": identity_id, "tags": case_tags,
                      "synthetic": case.get("synthetic", False), "inputs": {**{key: case[key] for key in INPUT_KEYS},
                                                                               "sources": case["sources"], "mask_channel": case["mask_channel"]},
                      "input_sha256": inputs, "current": {"result": case["current_result"], "run": current, "metrics": current_metrics},
                      "new": {"result": case["new_result"], "run": new, "metrics": new_metrics},
                      "delta_new_minus_current": deltas, "performance_delta_new_minus_current": performance_deltas,
                      "grid": str(grid_path)})
    aggregate = {}
    for key in cases[0]["current"]["metrics"]:
        valid = [case for case in cases if case["delta_new_minus_current"][key] is not None]
        aggregate[key] = {"paired_case_count": len(valid), "mean_delta_new_minus_current":
                          sum(case["delta_new_minus_current"][key] for case in valid) / len(valid) if valid else None}
    report = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "manifest_sha256": file_sha256(manifest), "case_count": len(cases),
              "purpose": "SYNTHETIC INTEGRATION FIXTURE - NOT A QUALITY BENCHMARK" if any(case["synthetic"] for case in cases) else "stored_output_comparison",
              "split_audit": {**split_audit, "training_manifests_checked": [str(Path(path).resolve()) for path in training_manifests],
                              "note": "Audit covers the declared enrolled corpus only; resolve identity aliases at enrollment"},
              "coverage": dict(sorted(tags.items())), "missing_recommended_tags": sorted(set(RECOMMENDED_TAGS) - set(tags)),
              "unavailable_metrics": UNAVAILABLE_METRICS,
              "metric_interpretation": {"deltas": "new minus current; negative is better for errors/latency/VRAM, positive for PSNR",
                                        "boundary_template_mae": "Pixel departure from original inside mask edge; not a realism score",
                                        "masked_reconstruction_psnr_db": "Null for exact reconstruction; inspect masked_reconstruction_exact"},
              "aggregate": aggregate, "cases": cases}
    save_json(output_dir / "report.json", report)
    return report
