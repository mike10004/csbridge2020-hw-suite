#!/usr/bin/env python3

import logging
import os
import tempfile
from unittest import TestCase

import hwsuite.tests
from hwsuite.build import _main, ProjectRootRequiredException
import hwsuite.init
import hwsuite.question
import subprocess
from subprocess import PIPE

_log = logging.getLogger(__name__)


class BuildTest(TestCase):

    def test_garden_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            proj_root = os.path.join(tempdir, 'my_homework_12')
            os.makedirs(proj_root)
            hwsuite.init._main(proj_root)
            hwsuite.question._main_raw(proj_root, 'q1')
            retcode = _main(proj_root)
            self.assertEqual(0, retcode)
            q_exec = os.path.join(proj_root, 'q1', 'cmake-build', 'q1')
            self.assertTrue(os.path.isfile(q_exec))
            proc = subprocess.run([q_exec], stdout=PIPE, stderr=PIPE)
            self.assertEqual(0, proc.returncode)
            self.assertEqual("q1 executed", proc.stdout.decode('utf8').strip())

    def test_prohibit_non_root(self):
        with tempfile.TemporaryDirectory() as tempdir:
            proj_root = os.path.join(tempdir, 'my_homework_12')
            os.makedirs(proj_root)
            hwsuite.tests.touch_all(proj_root, [hwsuite.CFG_FILENAME, 'q1/main.cpp', 'q1/question.md'])
            try:
                _main(os.path.join(proj_root, 'q1'))
                self.fail("should throw ProjectRootRequiredException")
            except ProjectRootRequiredException:
                pass