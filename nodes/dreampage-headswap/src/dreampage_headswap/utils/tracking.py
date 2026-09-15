from __future__ import annotations
import json
from pathlib import Path


class Tracker:
    def log(self, step: int, metrics: dict) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class JsonlTracker(Tracker):
    """Local-only metrics by default; never uploads images, identities or customer data."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a", encoding="utf-8")

    def log(self, step: int, metrics: dict) -> None:
        self.file.write(json.dumps({"step": step, **metrics}, allow_nan=False) + "\n")
        self.file.flush()

    def close(self) -> None:
        self.file.close()


class NullTracker(Tracker):
    def log(self, step: int, metrics: dict) -> None:
        pass


class TensorBoardTracker(Tracker):
    def __init__(self, directory):
        try:
            from torch.utils.tensorboard import SummaryWriter
        except ImportError as exc:
            raise RuntimeError("TensorBoard tracking requires the optional tensorboard package") from exc
        self.writer = SummaryWriter(str(directory))

    def log(self, step: int, metrics: dict) -> None:
        for name, value in metrics.items():
            if isinstance(value, (float, int)):
                self.writer.add_scalar(name, value, step)

    def close(self) -> None:
        self.writer.close()
