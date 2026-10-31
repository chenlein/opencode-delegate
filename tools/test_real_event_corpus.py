"""Integrity checks for multi-version reviewed event corpora; no model/network."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from check_real_events import ROOT, fixture_files


class CorpusIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'validation-fixtures/opencode-v223'
        shutil.copytree(ROOT / 'validation-fixtures/opencode-v223', self.folder)

    def test_all_current_versions_are_packaged(self):
        files = fixture_files()
        self.assertEqual({p.parent.name for p in files if p.name == 'manifest.json'},
                         {'opencode-v223', 'opencode-v225'})

    def test_historical_corpus_remains_valid(self):
        self.assertTrue(fixture_files(self.root))

    def test_changed_capture_is_rejected(self):
        next(self.folder.glob('*.ndjson')).write_text('{}\n')
        with self.assertRaises(ValueError): fixture_files(self.root)

    def test_unreviewed_extra_file_is_rejected(self):
        (self.folder / 'raw.log').write_text('not reviewed')
        with self.assertRaises(ValueError): fixture_files(self.root)

    def test_test_path_cannot_escape_manifest(self):
        p = self.folder / 'manifest.json'
        value = json.loads(p.read_text())
        value['tests'][0]['file'] = '../unreviewed.ndjson'
        p.write_text(json.dumps(value))
        with self.assertRaises(ValueError): fixture_files(self.root)

    def test_symlink_corpus_directory_is_rejected(self):
        outside = self.root / 'outside'
        self.folder.rename(outside)
        self.folder.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): fixture_files(self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
