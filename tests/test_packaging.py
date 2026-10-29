"""Release resources must survive the source-distribution-to-wheel build."""

import tomllib
from pathlib import Path


def test_sdist_includes_every_forced_wheel_resource():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    targets = config["tool"]["hatch"]["build"]["targets"]
    included = [Path(entry) for entry in targets["sdist"]["include"]]

    for source in targets["wheel"]["force-include"]:
        path = Path(source)
        assert (root / path).exists(), f"Missing wheel resource: {source}"
        assert any(path == entry or entry in path.parents for entry in included), (
            f"Wheel resource missing from sdist: {source}"
        )
