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
from hwsuite.init import do_init, _GITIGNORE_TEXT, _DEFAULT_SAFETY_MODE
import hwsuite.tests


_log = logging.getLogger(__name__)


class InitTest(TestCase):

    def test_append_gitignore(self):
        with tempfile.TemporaryDirectory() as tempdir:
            proj_root = os.path.join(tempdir, 'my_homework_12')
            os.makedirs(proj_root)
            pre_lines = ["/foo/", "bar.txt"]
            gitignore_file = hwsuite.tests.write_text_file("\n".join(pre_lines), os.path.join(proj_root, '.gitignore'))
            retcode = do_init(proj_root, 'hw12', safety_mode=_DEFAULT_SAFETY_MODE)
            self.assertEqual(0, retcode)
            expected_lines = [line + "\n" for line in (pre_lines + _GITIGNORE_TEXT.strip().split("\n"))]
            actual_lines = hwsuite.tests.read_file_lines(gitignore_file)
            self.assertListEqual(expected_lines, actual_lines)
