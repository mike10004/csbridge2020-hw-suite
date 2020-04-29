#!/usr/bin/env python3
import glob
import os
import sys
import tempfile
from typing import List, Collection, Set
from unittest import TestCase
from pathlib import Path
from hwsuite import stage
from hwsuite.stage import Stager, GitRunner
from random import random
import logging
import hwsuite.tests
from hwsuite.tests import touch_all

_log = logging.getLogger(__name__)


class FakeGitRunner(object):

    def __init__(self, output):
        self.output = output

    def run(self, args):
        return self.output

class StagerTest(TestCase):

    def test_map_to_destination(self):
        s = Stager('/home/somewhere/proj1')
        files = [
            '/home/somewhere/proj1/q1/main.cpp',
            '/home/somewhere/proj1/q2/main.cpp',
            '/home/somewhere/proj1/q2/library1.h',
            '/home/somewhere/proj1/q2/library2.h',
            '/home/somewhere/proj1/q2/library2.cpp',
            '/home/somewhere/proj1/q3/main.cpp',
        ]
        mapped = s.map_to_destination(files, '/path/to/stage', 'foo123_')
        self.assertDictEqual({
            '/home/somewhere/proj1/q1/main.cpp': '/path/to/stage/foo123_q1.cpp',
            '/home/somewhere/proj1/q2/main.cpp': '/path/to/stage/foo123_q2.cpp',
            '/home/somewhere/proj1/q2/library1.h': '/path/to/stage/library1.h',
            '/home/somewhere/proj1/q2/library2.h': '/path/to/stage/library2.h',
            '/home/somewhere/proj1/q2/library2.cpp': '/path/to/stage/library2.cpp',
            '/home/somewhere/proj1/q3/main.cpp': '/path/to/stage/foo123_q3.cpp',
        }, mapped)

    def test_stage_normal(self):
        fs_structure = """\
q1/main.cpp
q1/question.md
q1/test-cases.json
q2/main.cpp
q2/test-cases/input.txt
q2/test-cases/expected.txt
q3/question.md
q4/main.cpp
q4/.nostage
q4/question.md
"""
        with tempfile.TemporaryDirectory() as tempdir:
            Path(os.path.join(tempdir, '.hwconfig.json')).touch()
            touch_all(tempdir, fs_structure.split())
            prefix = 'abc123_hw_'
            stager = Stager(tempdir)
            nstaged = stager.stage(prefix)
            self.assertEqual(2, nstaged)
            expecteds = {
                os.path.join(tempdir, 'stage', prefix + 'q1.cpp'),
                os.path.join(tempdir, 'stage', prefix + 'q2.cpp'),
            }
            self._check_dir(tempdir, expecteds)

    def test_stage_manyfilesperdir(self):
        fs_structure = """\
q1/main.cpp
q1/question.md
q1/test-cases.json
q2/main.cpp
q2/library1.h
q2/library2.h
q2/library2.cpp
q2/test-cases/input.txt
q2/test-cases/expected.txt
some_tests/foo_test.cpp
test_q2/bar_test.cpp
q3/question.md
"""
        with tempfile.TemporaryDirectory() as tempdir:
            Path(os.path.join(tempdir, '.hwconfig.json')).touch()
            touch_all(tempdir, fs_structure.split())
            prefix = 'abc123_hw_'
            stager = Stager(tempdir)
            nstaged = stager.stage(prefix)
            self.assertEqual(5, nstaged)
            expecteds = {
                os.path.join(tempdir, 'stage', prefix + 'q1.cpp'),
                os.path.join(tempdir, 'stage', prefix + 'q2.cpp'),
                os.path.join(tempdir, 'stage', 'library1.h'),
                os.path.join(tempdir, 'stage', 'library2.h'),
                os.path.join(tempdir, 'stage', 'library2.cpp'),
            }
            self._check_dir(tempdir, expecteds)

    def _check_dir(self, proj_root: str, expecteds: Set[str]):
        stage_contents = glob.glob(os.path.join(proj_root, 'stage', '*'))
        founds = set()
        for expected in expecteds:
            if not os.path.isfile(expected):
                print(f"{expected} not found among {stage_contents}", file=sys.stderr)
            else:
                founds.add(expected)
        self.assertSetEqual(expecteds, founds)


class GitRunnerTest(TestCase):

    def test_config(self):
        runner = GitRunner()
        output = runner.run(['config', 'user.email'])
        self.assertFalse(not output.strip())


class ModuleTest(TestCase):

    def test__should_remove_yes(self):
        for line in [
            "int main() {      // stage:remove",
            "garbage     // stage:remove because reasons",
            "garbage     // stage:remove  ",
            "garbage     // stage: remove  ",
            "garbage     // stage:\tremove  ",
            "garbage// stage:remove  ",
            "garbage //      \t     stage:remove  ",
            "int main() {      // stage:cut",
            "garbage     // stage:cut because reasons",
            "garbage     // stage:cut  ",
            "garbage     // stage: cut  ",
            "garbage     // stage:\tcut  ",
            "garbage// stage:cut  ",
            "garbage //      \t     stage:cut  ",
        ]:
            with self.subTest():
                actual = stage._is_cut_any(line)
                self.assertTrue(actual)

    def test__should_remove_no(self):
        for line in [
            "int main() {",
            "garbage     // stage:something",
            "garbage     // stage: ",
            "garbage// stage: rmeove  ",
            "garbage// stage: ctu  ",
            "garbage //      \t     stage:remove2  ",
        ]:
            with self.subTest():
                actual = stage._is_cut_any(line)
                self.assertFalse(actual)

    def test__is_cut_start_yes(self):
        for line in [
            "blah blah // stage: cut start",
            "blah blah // stage: cut start please",
            "blah blah // stage:cut start",
            "blah blah // stage:cut start please",
        ]:
            with self.subTest():
                self.assertTrue(stage._is_cut_start(line), f"should parse as cut start: {repr(line)}")

    def test__is_cut_start_no(self):
        for line in [
            "blah blah // stage: cut stop",
            "blah blah // stage: cut blah",
            "blah blah // stage: cut",
            "blah blah // stage:cut stop",
            "blah blah // stage:cut blah",
            "blah blah // stage:cut",
        ]:
            with self.subTest():
                self.assertFalse(stage._is_cut_start(line))

    def test__is_cut_stop_yes(self):
        for line in [
            "blah blah // stage: cut stop",
            "blah blah // stage: cut stop please",
            "blah blah // stage:cut stop",
            "blah blah // stage:cut stop please",
        ]:
            with self.subTest():
                self.assertTrue(stage._is_cut_stop(line), f"should parse as cut stop: {repr(line)}")

    def test__is_cut_stop_no(self):
        for line in [
            "blah blah // stage: cut start",
            "blah blah // stage: cut blah",
            "blah blah // stage: cut",
            "blah blah // stage:cut start",
            "blah blah // stage:cut blah",
            "blah blah // stage:cut",
        ]:
            with self.subTest():
                self.assertFalse(stage._is_cut_stop(line))

    def test__transfer_lines(self):
        text = """\
int main()
{
   // stage: cut start
   int someJazz;
   cout << "hello" << endl;
   // stage: cut stop
   int a = 3 + 4;
   cout << a << endl;
   cout << "Praise be" << endl; // stage: cut
   return 0;
}
"""
        expected = """\
int main()
{
   int a = 3 + 4;
   cout << a << endl;
   return 0;
}
"""
        actual_lines = stage._transfer_lines(text.split("\n"))
        actual = "\n".join(actual_lines)
        self.assertEqual(expected, actual)

    def test_suggest_prefix_git(self):
        with tempfile.TemporaryDirectory() as proj_root:
            hwsuite.tests.touch_all(proj_root, ['.git/config'])
            cfg = {"question_model": {"project_name": "hw27"}}
            actual = stage.suggest_prefix(cfg, proj_root, git_runner = FakeGitRunner('abc123@nyu.edu\n'))
            self.assertEqual('abc123_hw27_', actual)

    def test_suggest_prefix_author(self):
        with tempfile.TemporaryDirectory() as proj_root:
            hwsuite.tests.touch_all(proj_root, ['.git/config'])
            cfg = {"question_model": {"project_name": "hw27", "author": 'def456@nyu.edu'}}
            actual = stage.suggest_prefix(cfg, proj_root, git_runner = FakeGitRunner('abc123@nyu.edu\n'))
            self.assertEqual('def456_hw27_', actual)

