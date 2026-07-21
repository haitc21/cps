"""Contract tree validation helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cps.contracts.semantic import validate_contract_semantics

CONTRACTS_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = CONTRACTS_ROOT / "checksums.json"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    fixture_count: int
    message: str = ""


def _contract_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for directory in ("fixtures", "jsonschema"):
        root = base / directory
        if root.exists():
            files.extend(
                path for path in root.rglob("*") if path.is_file() and path.name != ".gitkeep"
            )
    return sorted(files)


def compute_contract_checksums(base: Path) -> dict[str, str]:
    return {
        path.relative_to(base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _contract_files(base)
    }


def validate_contract_tree(root: Path | None = None) -> ValidationResult:
    """Validate fixtures+jsonschema checksums against a committed manifest (read-only)."""
    base = root or CONTRACTS_ROOT
    manifest_path = base / "checksums.json"
    computed = compute_contract_checksums(base)
    if not manifest_path.exists():
        return ValidationResult(False, len(computed), "missing checksums.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ValidationResult(False, len(computed), "invalid checksums.json")
    if manifest.get("files") != computed:
        return ValidationResult(False, len(computed), "contract checksum mismatch")
    _, semantic_error = validate_contract_semantics(base)
    if semantic_error is not None:
        return ValidationResult(False, len(computed), semantic_error)
    return ValidationResult(True, len(computed))


def write_contract_manifest(root: Path | None = None) -> ValidationResult:
    """Create or refresh checksums.json from fixtures/ and jsonschema/."""
    base = root or CONTRACTS_ROOT
    (base / "fixtures").mkdir(parents=True, exist_ok=True)
    (base / "jsonschema").mkdir(parents=True, exist_ok=True)
    computed = compute_contract_checksums(base)
    (base / "checksums.json").write_text(
        json.dumps({"files": computed}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ValidationResult(True, len(computed), "manifest written")


def main() -> None:
    result = validate_contract_tree()
    if not result.ok:
        raise SystemExit(f"contract validation failed: {result.message}")
    print(f"contracts ok ({result.fixture_count} files)")


if __name__ == "__main__":
    main()
