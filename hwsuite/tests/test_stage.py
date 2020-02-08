#!/usr/bin/env python3
import glob
import os
import sys
import tempfile
from typing import List
from unittest import TestCase
from pathlib import Path
from hwsuite import stage
import logging


_log = logging.getLogger(__name__)


def _touch_all(parent, relative_paths: List[str]):
    for relpath in relative_paths:
        abspath = os.path.join(parent, relpath)
        if abspath.endswith('/'):  # depends on Posix-like file separator char
            os.makedirs(abspath, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(abspath), exist_ok=True)
            path = Path(abspath)
            path.touch()


class StageTest(TestCase):

    def test_stage_normal(self):
        fs_structure = """\
q1/main.cpp
q1/question.md
q1/test-cases.json
q2/main.cpp
q2/test-cases/input.txt
q2/test-cases/expected.txt
q3/question.md
"""
        with tempfile.TemporaryDirectory() as tempdir:
            Path(os.path.join(tempdir, '.hwconfig.json')).touch()
            _touch_all(tempdir, fs_structure.split())
            prefix = 'abc123_hw_'
            nstaged = stage.stage(tempdir, prefix)
            self.assertEqual(2, nstaged)
            expecteds = {
                os.path.join(tempdir, 'stage', prefix + 'q1.cpp'),
                os.path.join(tempdir, 'stage', prefix + 'q2.cpp'),
            }
            stage_contents = glob.glob(os.path.join(tempdir, 'stage', '*'))
            founds = set()
            for expected in expecteds:
                if not os.path.isfile(expected):
                    print(f"{expected} not found among {stage_contents}", file=sys.stderr)
                else:
                    founds.add(expected)
            self.assertSetEqual(expecteds, founds)

    def test__should_remove_yes(self):
        for line in [
            "int main() {      // stage:remove",
            "garbage     // stage:remove because reasons",
            "garbage     // stage:remove  ",
            "garbage     // stage: remove  ",
            "garbage     // stage:\tremove  ",
            "garbage// stage:remove  ",
            "garbage //      \t     stage:remove  ",
        ]:
            with self.subTest():
                actual = stage._should_remove(line)
                self.assertTrue(actual)

    def test__should_remove_no(self):
        for line in [
            "int main() {",
            "garbage     // stage:something",
            "garbage     // stage: ",
            "garbage// stage: rmeove  ",
            "garbage //      \t     stage:remove2  ",
        ]:
            with self.subTest():
                actual = stage._should_remove(line)
                self.assertFalse(actual)