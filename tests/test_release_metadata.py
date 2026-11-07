"""Checks for the release metadata and validation workflow."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "lite_resources"


class ReleaseMetadataTest(unittest.TestCase):
    """The commit a later GitHub release will point at."""

    def test_manifest_version_and_required_keys(self) -> None:
        """Manifest has a semantic version and keeps the HACS keys."""
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], "lite_resources")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["name"], "Lite Resources")
        for key in ("documentation", "issue_tracker", "codeowners"):
            self.assertTrue(manifest.get(key), key)
        self.assertEqual(
            manifest["documentation"], "https://github.com/evski/ha-lite-resources"
        )
        self.assertEqual(
            manifest["issue_tracker"],
            "https://github.com/evski/ha-lite-resources/issues",
        )

    def test_hacs_manifest_has_name(self) -> None:
        """hacs.json has the required name."""
        hacs = json.loads((ROOT / "hacs.json").read_text())
        self.assertEqual(hacs["name"], "Lite Resources")
        self.assertNotIn("country", hacs)

    def test_changelog_records_patch(self) -> None:
        """The changelog has an entry for the manifest version."""
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn(f"## {manifest['version']}", changelog)
        self.assertIn("11:39:18 GMT", changelog)

    def test_validation_workflow_has_no_ignored_checks(self) -> None:
        """Validate runs hassfest and HACS with no ignore list."""
        workflow = (ROOT / ".github" / "workflows" / "validate.yaml").read_text()
        self.assertIn("home-assistant/actions/hassfest@master", workflow)
        self.assertIn("hacs/action@main", workflow)
        self.assertIn("category: integration", workflow)
        self.assertNotIn("ignore:", workflow)
        self.assertNotIn("ignore ", workflow)

    def test_brand_icon_present(self) -> None:
        """The brands check looks for brand/icon.png."""
        icon = INTEGRATION / "brand" / "icon.png"
        self.assertTrue(icon.is_file())
        self.assertGreater(icon.stat().st_size, 0)

    def test_readme_says_release_follows_validation(self) -> None:
        """Release steps tell a maintainer to publish after Validate succeeds."""
        readme = (ROOT / "README.md").read_text()
        self.assertIn("## Releasing", readme)
        self.assertIn("after the Validate workflow on that commit has succeeded", readme)
        self.assertIn("42369085242", readme)

    def test_single_integration_package(self) -> None:
        """HACS manages one directory under custom_components."""
        packages = [
            path
            for path in (ROOT / "custom_components").iterdir()
            if path.is_dir() and not path.name.startswith("__")
        ]
        self.assertEqual([path.name for path in packages], ["lite_resources"])


if __name__ == "__main__":
    unittest.main()
