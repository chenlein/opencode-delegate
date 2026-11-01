"""Release evidence inclusion and fail-closed integrity checks, no model calls."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from build_release import ROOT, VERSION, evidence_files


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root / 'docs/evidence/mac-rc8'
        shutil.copytree(ROOT / 'docs/evidence/mac-rc8', self.folder)

    def test_release_contains_all_manifest_evidence(self):
        output = self.root / 'release.zip'
        result = subprocess.run([sys.executable, str(ROOT / 'tools/build_release.py'),
                                 '--check', '--output', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(output) as archive:
            for path in evidence_files():
                name = 'opencode-delegate-' + VERSION + '/' + path.relative_to(ROOT).as_posix()
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),
                                 hashlib.sha256(path.read_bytes()).hexdigest())

    def test_changed_evidence_rejected(self):
        (self.folder / 'ROOT_REVIEW.json').write_text('{}\n')
        with self.assertRaises(ValueError): evidence_files(self.root)

    def test_extra_runtime_file_rejected(self):
        (self.folder / 'raw.log').write_text('unreviewed runtime content')
        with self.assertRaises(ValueError): evidence_files(self.root)

    def test_parent_escape_rejected(self):
        (self.folder / 'SHA256SUMS.txt').write_text('0' * 64 + '  ../outside.txt\n')
        with self.assertRaises(ValueError): evidence_files(self.root)

    def test_symlink_directory_rejected(self):
        source = self.folder / 'SOURCE'
        outside = self.root / 'outside'
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): evidence_files(self.root)

    def test_benign_root_alias_supported(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(evidence_files(alias), evidence_files(self.root))


if __name__ == '__main__':
    unittest.main(verbosity=2)
