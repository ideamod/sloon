"""Generate deterministic system dependency specification documents."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
GENERATED_RELATIVE_PATH = Path(".generated/dependency_specs.md")
_SYSTEM_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class GenerationError(Exception):
    """Raised when dependency specification input is invalid."""


@dataclass(frozen=True)
class GeneratedDocument:
    path: Path
    content: str


def _display_path(path: Path, repository_root: Path) -> str:
    try:
        return path.relative_to(repository_root).as_posix()
    except ValueError:
        return path.as_posix()


def _strip_yaml_comment(value: str) -> str:
    """Strip comments from the unquoted scalar subset accepted by manifests."""
    return value.split(" #", 1)[0].rstrip()


def _parse_name(value: str, path: Path, line_number: int) -> str:
    value = _strip_yaml_comment(value.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if not _SYSTEM_NAME.fullmatch(value):
        raise GenerationError(
            f"{path}: line {line_number}: invalid dependency name {value!r}"
        )
    return value


def parse_manifest(path: Path) -> list[str]:
    """Parse the repository's deliberately small dependencies.yaml schema."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise GenerationError(f"cannot read manifest {path}: {error}") from error

    if "\t" in text:
        raise GenerationError(f"{path}: tabs are not valid manifest indentation")

    meaningful = [
        (number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not meaningful:
        raise GenerationError(f"{path}: expected a dependencies key")

    first_number, first_line = meaningful[0]
    match = re.fullmatch(r"dependencies\s*:\s*(.*?)\s*", first_line)
    if match is None:
        raise GenerationError(
            f"{path}: line {first_number}: expected top-level 'dependencies:'"
        )

    inline = _strip_yaml_comment(match.group(1))
    dependencies: list[str] = []
    if inline:
        if not (inline.startswith("[") and inline.endswith("]")):
            raise GenerationError(
                f"{path}: line {first_number}: dependencies must be a YAML list"
            )
        body = inline[1:-1].strip()
        if body:
            dependencies = [
                _parse_name(item, path, first_number) for item in body.split(",")
            ]
        if len(meaningful) != 1:
            number, _ = meaningful[1]
            raise GenerationError(f"{path}: line {number}: unexpected content")
    else:
        for number, line in meaningful[1:]:
            item_match = re.fullmatch(r"\s+-\s+(.+?)\s*", line)
            if item_match is None:
                raise GenerationError(
                    f"{path}: line {number}: expected an indented dependency list item"
                )
            dependencies.append(_parse_name(item_match.group(1), path, number))
        if len(meaningful) == 1:
            raise GenerationError(
                f"{path}: line {first_number}: dependencies must be a YAML list"
            )

    duplicates = sorted(
        name for name in set(dependencies) if dependencies.count(name) > 1
    )
    if duplicates:
        raise GenerationError(
            f"{path}: duplicate dependencies: {', '.join(duplicates)}"
        )
    return dependencies


def _system_directories(repository_root: Path) -> dict[str, Path]:
    systems_root = repository_root / "systems"
    try:
        directories = {
            path.name: path
            for path in systems_root.iterdir()
            if path.is_dir()
            and not path.name.startswith(".")
            and path.name != "__pycache__"
        }
    except OSError as error:
        raise GenerationError(f"cannot inspect {systems_root}: {error}") from error
    if not directories:
        raise GenerationError(f"no systems found under {systems_root}")
    return directories


def _public_specification_files(system_directory: Path) -> list[Path]:
    spec_directory = system_directory / "spec"
    if not spec_directory.is_dir():
        raise GenerationError(f"missing specification directory: {spec_directory}")
    try:
        files = sorted(
            (
                path
                for path in spec_directory.rglob("*")
                if path.is_file()
                and not any(part.startswith(".") for part in path.relative_to(spec_directory).parts)
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
            ),
            key=lambda path: path.relative_to(spec_directory).as_posix(),
        )
    except OSError as error:
        raise GenerationError(f"cannot inspect {spec_directory}: {error}") from error
    if not files:
        raise GenerationError(
            f"no public specification files found in {spec_directory}"
        )
    return files


def _read_specification(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise GenerationError(f"cannot read specification file {path}: {error}") from error


def _fence_for(content: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def _render_document(
    dependencies: list[str],
    systems: dict[str, Path],
    repository_root: Path,
) -> str:
    chunks = ["# Dependency Specifications\n\n"]
    if not dependencies:
        chunks.append("No direct dependencies are declared.\n")
        return "".join(chunks)

    for dependency in sorted(dependencies):
        chunks.append(f"## {dependency}\n\n")
        for spec_path in _public_specification_files(systems[dependency]):
            content = _read_specification(spec_path)
            source_path = _display_path(spec_path, repository_root)
            language = "python" if spec_path.suffix == ".py" else "text"
            fence = _fence_for(content)
            chunks.extend(
                [
                    f"### `{source_path}`\n\n",
                    f"{fence}{language}\n",
                    content,
                ]
            )
            if not content.endswith("\n"):
                chunks.append("\n")
            chunks.append(f"{fence}\n\n")
    return "".join(chunks)


def build_documents(repository_root: Path = REPOSITORY_ROOT) -> list[GeneratedDocument]:
    """Validate all inputs and build every generated document in memory."""
    repository_root = repository_root.resolve()
    systems = _system_directories(repository_root)
    manifests: dict[str, list[str]] = {}

    for system_name in sorted(systems):
        manifest_path = systems[system_name] / "dependencies.yaml"
        if not manifest_path.is_file():
            raise GenerationError(f"missing dependency manifest: {manifest_path}")
        dependencies = parse_manifest(manifest_path)
        for dependency in dependencies:
            if dependency == system_name:
                raise GenerationError(
                    f"{manifest_path}: system {system_name!r} depends on itself"
                )
            if dependency not in systems:
                raise GenerationError(
                    f"{manifest_path}: unknown dependency {dependency!r}"
                )
        manifests[system_name] = dependencies

    documents = []
    for system_name in sorted(systems):
        content = _render_document(manifests[system_name], systems, repository_root)
        documents.append(
            GeneratedDocument(
                systems[system_name] / GENERATED_RELATIVE_PATH,
                content,
            )
        )
    return documents


def generate(repository_root: Path = REPOSITORY_ROOT, *, check: bool = False) -> list[Path]:
    """Generate documents, returning missing/stale paths in check mode."""
    repository_root = repository_root.resolve()
    documents = build_documents(repository_root)
    affected: list[Path] = []
    for document in documents:
        try:
            current = document.path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            current = None
        except (OSError, UnicodeError) as error:
            raise GenerationError(
                f"cannot read generated file {document.path}: {error}"
            ) from error
        if current == document.content:
            continue
        affected.append(document.path)
        if not check:
            try:
                document.path.parent.mkdir(parents=True, exist_ok=True)
                document.path.write_bytes(document.content.encode("utf-8"))
            except OSError as error:
                raise GenerationError(
                    f"cannot write generated file {document.path}: {error}"
                ) from error
    return affected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate public specifications for direct system dependencies."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report missing or stale generated files without modifying them",
    )
    arguments = parser.parse_args(argv)
    try:
        affected = generate(check=arguments.check)
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if arguments.check and affected:
        for path in affected:
            print(f"stale: {_display_path(path, REPOSITORY_ROOT)}", file=sys.stderr)
        return 1
    if not arguments.check:
        for path in affected:
            print(f"updated: {_display_path(path, REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
