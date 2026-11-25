#!/usr/bin/env python3
"""scripts/fpvos-version: the one version every fpvOS image reports - the tag
on a clean release commit, VERSION and the commit anywhere else, and VERSION
alone where there is no git to ask."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'fpvos-version'
GIT = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
           GIT_COMMITTER_EMAIL='t@t', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')


class FpvosVersion(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.tree = Path(temp.name) / 'tree'
        (self.tree / 'scripts').mkdir(parents=True)
        shutil.copy(SCRIPT, self.tree / 'scripts/fpvos-version')
        (self.tree / 'VERSION').write_text('2026.11.beta1\n')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.tree), *args], env=GIT, check=True,
                              capture_output=True, text=True).stdout.strip()

    def version(self, *args):
        r = subprocess.run(['sh', str(self.tree / 'scripts/fpvos-version'), *args], env=GIT,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self):
        self.git('init', '-q')
        self.git('add', '.')
        self.git('commit', '-qm', 'tree')
        return self.git('rev-parse', '--short=8', 'HEAD')

    def test_without_git_it_is_VERSION(self):
        self.assertEqual(self.version(), '2026.11.beta1')

    def test_between_tags_it_is_VERSION_and_the_commit(self):
        sha = self.commit()
        self.assertEqual(self.version(), f'2026.11.beta1+g{sha}')

    def test_uncommitted_changes_are_dirty(self):
        sha = self.commit()
        (self.tree / 'VERSION').write_text('2026.11.beta1\n\n')
        self.assertEqual(self.version(), f'2026.11.beta1+g{sha}-dirty')

    def test_untracked_files_are_not_dirty(self):
        sha = self.commit()
        (self.tree / 'scratch').write_text('x')
        self.assertEqual(self.version(), f'2026.11.beta1+g{sha}')

    def test_a_clean_tag_is_the_tag(self):
        self.commit()
        self.git('tag', '2026.11.beta1')
        self.assertEqual(self.version(), '2026.11.beta1')

    def test_a_dirty_tag_is_not_the_release(self):
        sha = self.commit()
        self.git('tag', '2026.11.beta1')
        (self.tree / 'VERSION').write_text('changed\n')
        self.assertEqual(self.version(), f'changed+g{sha}-dirty')

    def test_another_tree(self):
        sha = self.commit()
        elsewhere = Path(self.tree.parent) / 'elsewhere.sh'
        shutil.copy(SCRIPT, elsewhere)
        r = subprocess.run(['sh', str(elsewhere), str(self.tree)], env=GIT, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), f'2026.11.beta1+g{sha}')

    def test_fits_the_updater_field(self):
        sha = self.commit()
        (self.tree / 'VERSION').write_text('2026.11.beta12\n')
        self.assertLessEqual(len(self.version()), 31)
        self.assertTrue(self.version().endswith(f'+g{sha}-dirty'))


if __name__ == '__main__':
    unittest.main()
