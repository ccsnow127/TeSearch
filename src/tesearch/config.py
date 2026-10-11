"""Tunables of the search and of the measurement harness."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"


@dataclass(frozen=True)
class Config:
    # --- landing model and acquisition -------------------------------------
    sigma: float = 0.10        # spread of realized suite size around the request, in log units
    eta: float = 0.2           # step size when the per-module size bias is updated
    alpha_q: float = 0.3       # smoothing rate of a niche's value estimate
    c_e: float = 0.5           # weight of the exploration bonus
    H: float = 0.85            # quality a module must reach before size pressure starts

    # --- niche grid and request clamping -----------------------------------
    gamma: int = 4             # how many niches the grid extends above the seed anchor
    kappa_a: float = 2.5       # a request stays within this factor of the niche centre

    # --- budget ------------------------------------------------------------
    budget: int = 50           # LLM calls per module, seeds included
    n_seed: int = 3            # opening generations made without naming a size

    # --- mutants -----------------------------------------------------------
    search_mutants: int = 60   # mutants the search is scored against
    eval_mutants: int = 800    # held-out mutants, used only on the delivered suite
    mutant_seed: int = 0       # makes the split between the two sets reproducible

    # --- backbone ----------------------------------------------------------
    model: str = "gpt-5.4"
    temperature: float = 0.7
    max_tokens: int = 16000

    @property
    def rho(self) -> float:
        """Ratio between consecutive niche boundaries: one niche spans ±sigma."""
        return math.exp(2.0 * self.sigma)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_CONFIG, **overrides) -> "Config":
        """Read a config file laid out like ``configs/default.yaml``: sections are
        only for readability, every leaf key is a field of this class. Keyword
        overrides (from the command line) win over the file."""
        import yaml

        raw = yaml.safe_load(Path(path).read_text()) or {}
        flat: dict = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                flat.update(value)
            else:
                flat[key] = value
        known = {f.name for f in fields(cls)}
        unknown = set(flat) - known
        if unknown:
            raise ValueError(f"{path}: unknown config keys {sorted(unknown)}")
        flat.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**flat)
