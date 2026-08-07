import pathlib
import tomllib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseFilesTests(unittest.TestCase):
    def test_project_metadata_and_pinned_dependencies(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)["project"]

        self.assertEqual(project["name"], "chord-2go-spotify")
        self.assertEqual(project["version"], "0.1.0")
        self.assertIn("bleak==3.0.2", project["dependencies"])

        requirements = (ROOT / "requirements-build.txt").read_text()
        self.assertIn("pyinstaller==6.21.0", requirements)

    def test_release_workflow_builds_all_host_archives(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        for archive in (
            "chord-2go-spotify-macos-arm64",
            "chord-2go-spotify-macos-x86_64",
            "chord-2go-spotify-windows-x86_64",
        ):
            self.assertIn(archive, workflow)

        self.assertIn("SHA256SUMS.txt", workflow)
        self.assertIn("attest-build-provenance", workflow)
        self.assertIn("cargo-zigbuild --version 0.21.8", workflow)
        self.assertIn("LICENSE README.md", workflow)
        self.assertIn("THIRD_PARTY_NOTICES.md", workflow)

    def test_librespot_source_is_immutable_and_stable_only(self):
        build_script = (ROOT / "scripts/build-librespot.sh").read_text()
        self.assertIn(
            "d36f9f1907e8cc9d68a93f8ebc6b627b1bf7267d",
            build_script,
        )
        self.assertIn("armv7-unknown-linux-musleabihf", build_script)

        service = ROOT / "payload/librespot.service"
        if service.exists():
            contents = service.read_text().lower()
            self.assertIn("--bitrate 320", contents)
            self.assertNotIn("--bitrate lossless", contents)
            self.assertNotIn("playplay", contents)

    def test_documentation_does_not_claim_lossless_support(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("not Spotify Lossless", readme)
        self.assertIn("Ogg Vorbis up to 320 kbps", readme)


if __name__ == "__main__":
    unittest.main()
