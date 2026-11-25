from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.generate_dependency_specs import GenerationError, build_documents, generate


class DependencySpecGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "systems").mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_system(
        self,
        name: str,
        dependencies: list[str],
        specs: dict[str, str] | None = None,
    ) -> Path:
        system = self.root / "systems" / name
        system.mkdir()
        if dependencies:
            manifest = "dependencies:\n" + "".join(
                f"  - {dependency}\n" for dependency in dependencies
            )
        else:
            manifest = "dependencies: []\n"
        (system / "dependencies.yaml").write_text(manifest, encoding="utf-8")
        if specs is not None:
            for relative_path, content in specs.items():
                path = system / "spec" / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        return system

    def document_for(self, system_name: str) -> str:
        documents = build_documents(self.root)
        document = next(
            item for item in documents if item.path.parent.parent.name == system_name
        )
        return document.content

    def test_includes_complete_direct_specs_and_excludes_undeclared_transitive_specs(self) -> None:
        self.add_system("alpha", ["beta"], {"api.py": "alpha api\n"})
        self.add_system(
            "beta",
            ["gamma"],
            {"schema.py": "  exact beta whitespace  \n", "api.py": "beta api\n"},
        )
        self.add_system("gamma", [], {"api.py": "gamma api\n"})

        content = self.document_for("alpha")

        self.assertIn("## beta", content)
        self.assertIn("  exact beta whitespace  \n", content)
        self.assertIn("beta api\n", content)
        self.assertNotIn("## gamma", content)
        self.assertNotIn("gamma api", content)
        self.assertNotIn("alpha api", content)

    def test_dependencies_and_specification_files_are_alphabetical(self) -> None:
        self.add_system("consumer", ["zulu", "alpha"], {"api.py": "consumer\n"})
        self.add_system("zulu", [], {"z.py": "z\n", "a.py": "a\n"})
        self.add_system("alpha", [], {"api.py": "alpha\n"})

        content = self.document_for("consumer")

        self.assertLess(content.index("## alpha"), content.index("## zulu"))
        self.assertLess(content.index("spec/a.py"), content.index("spec/z.py"))

    def test_private_cache_and_bytecode_files_are_excluded(self) -> None:
        self.add_system("consumer", ["dependency"], {"api.py": "public\n"})
        dependency = self.add_system(
            "dependency",
            [],
            {
                "api.py": "public\n",
                ".private.py": "private\n",
                "__pycache__/api.pyc": "cache\n",
            },
        )
        (dependency / "spec" / "ignored.pyo").write_text("bytecode", encoding="utf-8")

        content = self.document_for("consumer")

        self.assertIn("public", content)
        self.assertNotIn("private", content)
        self.assertNotIn("cache", content)
        self.assertNotIn("bytecode", content)

    def test_source_line_endings_and_whitespace_are_preserved(self) -> None:
        self.add_system("consumer", ["dependency"], {"api.py": "consumer\n"})
        dependency = self.add_system("dependency", [], {"api.py": "placeholder"})
        source = b"first  \r\n\tsecond\r\n"
        (dependency / "spec/api.py").write_bytes(source)

        content = self.document_for("consumer").encode("utf-8")

        self.assertIn(b"```python\n" + source + b"```\n", content)

    def test_empty_dependencies_have_minimal_document(self) -> None:
        self.add_system("empty", [], {"api.py": "unused\n"})
        self.assertEqual(
            self.document_for("empty"),
            "# Dependency Specifications\n\nNo direct dependencies are declared.\n",
        )

    def test_output_is_deterministic_and_identical_files_are_not_rewritten(self) -> None:
        self.add_system("alpha", [], {"api.py": "alpha\n"})
        generate(self.root)
        output = self.root / "systems/alpha/.generated/dependency_specs.md"
        first_content = output.read_bytes()
        first_mtime = output.stat().st_mtime_ns

        generate(self.root)

        self.assertEqual(output.read_bytes(), first_content)
        self.assertEqual(output.stat().st_mtime_ns, first_mtime)

    def test_check_reports_missing_file_without_creating_directory(self) -> None:
        self.add_system("alpha", [], {"api.py": "alpha\n"})
        generated_directory = self.root / "systems/alpha/.generated"

        affected = generate(self.root, check=True)

        self.assertEqual(
            affected, [(generated_directory / "dependency_specs.md").resolve()]
        )
        self.assertFalse(generated_directory.exists())

    def test_check_reports_stale_file_without_modifying_it(self) -> None:
        system = self.add_system("alpha", [], {"api.py": "alpha\n"})
        generated = system / ".generated/dependency_specs.md"
        generated.parent.mkdir()
        generated.write_text("stale", encoding="utf-8")
        original_mtime = generated.stat().st_mtime_ns

        affected = generate(self.root, check=True)

        self.assertEqual(affected, [generated.resolve()])
        self.assertEqual(generated.read_text(encoding="utf-8"), "stale")
        self.assertEqual(generated.stat().st_mtime_ns, original_mtime)

    def test_invalid_manifest_and_duplicate_dependencies_fail(self) -> None:
        system = self.add_system("alpha", [], {"api.py": "alpha\n"})
        (system / "dependencies.yaml").write_text("wrong: []\n", encoding="utf-8")
        with self.assertRaisesRegex(GenerationError, "expected top-level"):
            build_documents(self.root)

        (system / "dependencies.yaml").write_text(
            "dependencies: [beta, beta]\n", encoding="utf-8"
        )
        self.add_system("beta", [], {"api.py": "beta\n"})
        with self.assertRaisesRegex(GenerationError, "duplicate dependencies"):
            build_documents(self.root)

    def test_unknown_and_self_dependencies_fail(self) -> None:
        system = self.add_system("alpha", ["missing"], {"api.py": "alpha\n"})
        with self.assertRaisesRegex(GenerationError, "unknown dependency"):
            build_documents(self.root)

        (system / "dependencies.yaml").write_text(
            "dependencies: [alpha]\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(GenerationError, "depends on itself"):
            build_documents(self.root)

    def test_missing_manifest_and_specification_directory_fail(self) -> None:
        system = self.root / "systems/alpha"
        system.mkdir()
        with self.assertRaisesRegex(GenerationError, "missing dependency manifest"):
            build_documents(self.root)

        (system / "dependencies.yaml").write_text(
            "dependencies: [beta]\n", encoding="utf-8"
        )
        self.add_system("beta", [], None)
        with self.assertRaisesRegex(GenerationError, "missing specification directory"):
            build_documents(self.root)

    def test_unreadable_specification_file_fails_clearly(self) -> None:
        self.add_system("consumer", ["dependency"], {"api.py": "consumer\n"})
        dependency = self.add_system("dependency", [], {"api.py": "dependency\n"})
        target = (dependency / "spec/api.py").resolve()
        original_read_bytes = Path.read_bytes

        def fail_target(path: Path, *args: object, **kwargs: object) -> bytes:
            if path == target:
                raise OSError("denied")
            return original_read_bytes(path, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", fail_target):
            with self.assertRaisesRegex(GenerationError, "cannot read specification"):
                build_documents(self.root)


if __name__ == "__main__":
    unittest.main()
