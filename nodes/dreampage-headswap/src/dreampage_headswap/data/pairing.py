"""Deterministic identity-level splitting and extensible self-supervised pairing."""
from __future__ import annotations

import hashlib
import random
from typing import Callable

from .records import IdentityRecord


def identity_split(identity_id: str, seed: int = 0, train: float = 0.8,
                   validation: float = 0.1) -> str:
    if not 0 <= train <= 1 or not 0 <= validation <= 1 or train + validation > 1:
        raise ValueError("Invalid split fractions")
    digest = hashlib.sha256(f"{seed}:{identity_id}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / 2**64
    return "train" if fraction < train else "validation" if fraction < train + validation else "test"


def same_identity_pairs(identity: IdentityRecord, seed: int) -> list[tuple[int, int]]:
    pairs = [(source, target) for target, image in enumerate(identity.images)
             if image.headmask is not None for source in range(len(identity.images)) if source != target]
    random.Random(f"{seed}:{identity.identity_id}").shuffle(pairs)
    return pairs


PAIR_STRATEGIES: dict[str, Callable[[IdentityRecord, int], list[tuple[int, int]]]] = {
    "same_identity": same_identity_pairs,
}


def generate_pairs(identities: list[IdentityRecord], *, seed: int = 0,
                   strategy: str = "same_identity", max_pairs_per_identity: int | None = None,
                   train_fraction: float = 0.8, validation_fraction: float = 0.1) -> list[dict]:
    if strategy not in PAIR_STRATEGIES:
        raise ValueError(f"Unknown pair strategy {strategy!r}; register a reviewed strategy first")
    if max_pairs_per_identity is not None and max_pairs_per_identity < 1:
        raise ValueError("max_pairs_per_identity must be positive")
    output = []
    for identity in sorted(identities, key=lambda item: item.identity_id):
        # Sort captures so input JSON ordering never changes seeded pair selection.
        identity = IdentityRecord(identity.identity_id, sorted(identity.images, key=lambda image: image.image_id),
                                  identity.rights, identity.split, identity.age, identity.synthetic)
        split = identity.split or identity_split(identity.identity_id, seed, train_fraction, validation_fraction)
        pairs = PAIR_STRATEGIES[strategy](identity, seed)
        if not pairs:
            raise ValueError(f"{identity.identity_id}: no target has an authoritative headmask")
        for source_index, target_index in pairs[:max_pairs_per_identity]:
            source, target = identity.images[source_index], identity.images[target_index]
            digest = hashlib.sha256(f"{identity.identity_id}:{source.image_id}:{target.image_id}:{strategy}".encode()).hexdigest()[:20]
            row = {
                "schema_version": 1, "pair_id": digest, "identity_id": identity.identity_id,
                "split": split, "strategy": strategy, "source": str(source.path),
                "sources": [str(source.path)], "template": str(target.path),
                "headmask": str(target.headmask), "ground_truth": str(target.path),
                # The source's own mask, when enrolment supplied one. Identity training needs
                # both views framed the same way; otherwise it can learn "photo versus crop".
                **({"source_headmasks": [str(source.headmask)],
                    "source_mask_channels": [source.metadata.get("mask_channel", "red")]} if source.headmask else {}),
                "mask_channel": target.metadata.get("mask_channel", "red"),
                "rights": identity.rights, "synthetic": identity.synthetic,
                "target_metadata": target.metadata,
            }
            if identity.age is not None:
                row["age"] = identity.age
            output.append(row)
    return output
