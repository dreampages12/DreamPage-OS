"""Forbered offisielle 9B-komponenter og gjenbruk den lokale transformeren. Ingen trening."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
import shutil

from dreampage_headswap.model_target import KLEIN_9B, PROFILES, inspect_single_file
from dreampage_headswap.data.records import file_sha256


def main():
    from huggingface_hub import HfApi, snapshot_download
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", choices=sorted(PROFILES), default=KLEIN_9B)
    parser.add_argument("--revision", required=True, help="Eksakt offisiell commit, ikke main")
    parser.add_argument("--transformer", required=True, type=Path)
    parser.add_argument("--output-dir", default="local_data/models/flux-klein-9b", type=Path)
    parser.add_argument("--download", action="store_true", help="Uten dette vises bare inventaret")
    args = parser.parse_args()
    if len(args.revision) != 40 or any(c not in "0123456789abcdef" for c in args.revision):
        raise ValueError("Bruk en full commit-SHA for aa binde modellversjonen")
    inspect_single_file(args.transformer)
    info = HfApi().model_info(args.model_id, revision=args.revision, files_metadata=True)
    if info.sha != args.revision:
        raise ValueError("Modellrevisjonen samsvarer ikke")
    patterns = ["LICENSE*", "README.md", "model_index.json", "scheduler/*", "tokenizer/*",
                "text_encoder/*", "vae/*", "transformer/*.json"]
    files = [f for f in info.siblings if any(fnmatch(f.rfilename, p) for p in patterns)]
    standalone = [f for f in info.siblings if "/" not in f.rfilename and f.rfilename.endswith(".safetensors")]
    if len(standalone) != 1 or not standalone[0].lfs:
        raise ValueError("Forventet en offisiell enkeltfil med SHA256 for denne 9B-varianten")
    print(json.dumps({"model_id": args.model_id, "revision": info.sha, "gated": info.gated,
                      "component_bytes": sum(f.size for f in files), "files": [f.rfilename for f in files],
                      "transformer_reused": str(args.transformer), "download_requested": args.download}, indent=2))
    if not args.download:
        return
    # Verifiser modellen foer nye gigabyte lastes ned. Ikke last vektene i RAM.
    transformer_sha = file_sha256(args.transformer)
    if args.transformer.stat().st_size != standalone[0].size or transformer_sha != standalone[0].lfs.sha256:
        raise ValueError("Lokal 9B-fil er ikke den valgte offisielle varianten/revisjonen")
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    previous_receipt = root / "dreampage_provenance.json"
    if previous_receipt.exists():
        previous = json.loads(previous_receipt.read_text(encoding="utf-8"))
        if (previous.get("model_id"), previous.get("revision")) != (args.model_id, args.revision):
            raise ValueError("Mappa tilhoerer en annen modell/revisjon; velg en ny mappe")
    remaining = sum(f.size for f in files if not (root / f.rfilename).is_file())
    if shutil.disk_usage(root).free < remaining + 2 * 1024**3:
        raise ValueError("For lite ledig diskplass for 9B-komponentene")
    # Bruk bare kontoens eksisterende tilgang. Ingen vilkaar aksepteres automatisk.
    snapshot_download(args.model_id, revision=args.revision, local_dir=root,
                      allow_patterns=patterns, max_workers=2)
    verified = []
    for entry in files:
        p = root / entry.rfilename
        if p.stat().st_size != entry.size:
            raise ValueError("Feil filstoerrelse: " + entry.rfilename)
        digest = file_sha256(p)
        if entry.lfs:
            upstream, actual = entry.lfs.sha256, digest
        else:
            upstream = entry.blob_id
            actual = hashlib.sha1(f"blob {entry.size}\0".encode() + p.read_bytes()).hexdigest()
        if actual != upstream:
            raise ValueError("Offisiell filhash avviker: " + entry.rfilename)
        verified.append({"path": entry.rfilename, "bytes": entry.size, "sha256": digest, "upstream_hash": upstream})
    receipt = {"model_id": args.model_id, "revision": args.revision,
               "license": "FLUX Non-Commercial License", "commercial_use_reviewed": False,
               "review_note": "Kildeinnhold er verifisert; en separat kommersiell rettighetsavklaring er ikke antatt.",
               "license_source": f"https://huggingface.co/{args.model_id}/tree/{args.revision}",
               "retrieved_utc": datetime.now(timezone.utc).isoformat(), "files": verified,
               "transformer_source": {"path": standalone[0].rfilename, "sha256": transformer_sha,
                                      "bytes": args.transformer.stat().st_size},
               "training_started": False, "identity_quality_validated": False}
    target = root / "dreampage_provenance.json"
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        # Ikke overskriv en separat review-record ved gjentatt klargjoering.
        if (previous.get("model_id"), previous.get("revision"), previous.get("files"), previous.get("transformer_source")) == (receipt["model_id"], receipt["revision"], receipt["files"], receipt["transformer_source"]):
            for key in ("commercial_use_reviewed", "commercial_use_reference"):
                if key in previous:
                    receipt[key] = previous[key]
        else:
            raise ValueError("Mappa har en annen modellkvittering; velg en ny versjonert mappe")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    print(target)


if __name__ == "__main__":
    main()
