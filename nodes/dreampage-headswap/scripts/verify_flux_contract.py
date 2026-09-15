"""Execute optional real Diffusers tiny-config tests and save reproducible evidence."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runs/flux-contract/report.json")
    args = parser.parse_args()
    try:
        import diffusers
        import transformers
        import torch
        import huggingface_hub
    except ImportError as exc:
        raise SystemExit("Run this in the isolated FLUX contract environment; optional dependency missing: " + str(exc))
    spec = importlib.util.spec_from_file_location("test_flux_contract", ROOT / "tests" / "test_flux_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"passed": result.wasSuccessful() and not result.skipped, "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "versions": {"python": sys.version, "torch": torch.__version__, "diffusers": diffusers.__version__,
                     "transformers": transformers.__version__, "huggingface_hub": huggingface_hub.__version__},
        "runtime": {"python": sys.executable, "torch_path": torch.__file__, "diffusers_path": diffusers.__file__},
        "models": ["Flux2Transformer2DModel", "AutoencoderKLFlux2", "Qwen3ForCausalLM"],
        "scope": "Real library modules with tiny random configs and a toy local vocabulary; no downloaded model weights or face data",
        "pretrained_base_4b_executed": False, "identity_quality_validated": False,
        "evidence": module.CONTRACT_EVIDENCE,
        "sources": ["https://github.com/huggingface/diffusers/blob/v0.37.1/src/diffusers/pipelines/flux2/pipeline_flux2_klein.py",
                    "https://github.com/huggingface/diffusers/blob/v0.37.1/src/diffusers/models/transformers/transformer_flux2.py"]}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
