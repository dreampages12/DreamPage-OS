"""Rights-validated multi-image records, pair manifests and CPU preprocessing."""
from .records import IdentityRecord, ImageRecord, RightsMetadata, load_identities, validate_pair_manifests
from .pairing import generate_pairs, identity_split


def __getattr__(name):
    if name == "PairDataset":
        from .dataset import PairDataset
        return PairDataset
    raise AttributeError(name)


__all__ = ["IdentityRecord", "ImageRecord", "RightsMetadata", "load_identities", "validate_pair_manifests",
           "generate_pairs", "identity_split", "PairDataset"]
