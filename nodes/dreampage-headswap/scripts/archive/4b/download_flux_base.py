"""Fetch the audited, public BASE 4B Diffusers snapshot and verify every file.

Run in the isolated FLUX environment. No account token, remote Python code,
standalone duplicate checkpoint, or changes to the ComfyUI environment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

MODEL_ID = "black-forest-labs/FLUX.2-klein-base-4B"
REVISION = "a3b4f4849157f664bdbc776fd7453c2783562f4d"
PATTERNS = ["LICENSE.md", "README.md", "model_index.json", "scheduler/*",
            "text_encoder/*", "tokenizer/*", "transformer/*", "vae/*"]


def main():
    from fnmatch import fnmatch
    from huggingface_hub import HfApi, snapshot_download

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="local_data/models/flux-klein-base-4b")
    args = parser.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    info = HfApi().model_info(MODEL_ID, revision=REVISION, files_metadata=True, token=False)
    if info.sha != REVISION or info.gated:
        raise RuntimeError("Unexpected revision or access terms; download refused")
    if info.card_data.get("license") != "apache-2.0":
        raise RuntimeError("Upstream license metadata changed; review source before downloading")
    files = [f for f in info.siblings if any(fnmatch(f.rfilename, p) for p in PATTERNS)]
    total = sum(f.size for f in files)
    remaining = sum(f.size for f in files if not (root / f.rfilename).is_file())
    if shutil.disk_usage(root).free < remaining + 2 * 1024**3:
        raise RuntimeError("Insufficient free disk for snapshot plus 2 GiB margin")
    print(json.dumps({"event": "download_started", "model": MODEL_ID, "revision": REVISION,
                      "files": len(files), "total_bytes": total, "output": str(root)}), flush=True)
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=root, token=False,
                      allow_patterns=PATTERNS, max_workers=2)
    verified = []
    for entry in files:
        path = root / entry.rfilename
        if path.stat().st_size != entry.size:
            raise RuntimeError(f"Size mismatch: {entry.rfilename}")
        sha256 = hashlib.sha256()
        git_sha1 = hashlib.sha1(f"blob {entry.size}\0".encode())
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                sha256.update(block)
                git_sha1.update(block)
        expected = entry.lfs.sha256 if entry.lfs else entry.blob_id
        observed = sha256.hexdigest() if entry.lfs else git_sha1.hexdigest()
        if observed != expected:
            raise RuntimeError(f"Upstream content hash mismatch: {entry.rfilename}")
        verified.append({"path": entry.rfilename, "bytes": entry.size,
                         "sha256": sha256.hexdigest(), "upstream_hash": expected})
        print("Verified " + entry.rfilename, flush=True)
    provenance = {"model_id": MODEL_ID, "revision": REVISION, "license": "Apache-2.0",
        "commercial_use_reviewed": True,
        "license_source": f"https://huggingface.co/{MODEL_ID}/blob/{REVISION}/LICENSE.md",
        "review_scope": "Official publisher Apache-2.0 license and unmodified upstream content hashes; not a quality certification",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(), "files": verified,
        "pretrained_model_executed": False, "identity_quality_validated": False}
    destination = root / "dreampage_provenance.json"
    destination.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(json.dumps({"event": "download_verified", "provenance": str(destination),
                      "total_bytes": total, "files": len(files)}), flush=True)


if __name__ == "__main__":
    main()
