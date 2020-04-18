#!/usr/bin/env python3

import glob
import json
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
            retcode = do_init(proj_root, safety_mode=_DEFAULT_SAFETY_MODE, hwconfig={})
            self.assertEqual(0, retcode)
            expected_lines = [line + "\n" for line in (pre_lines + _GITIGNORE_TEXT.strip().split("\n"))]
            actual_lines = hwsuite.tests.read_file_lines(gitignore_file)
            self.assertListEqual(expected_lines, actual_lines)

    def test_config_params_name_and_author(self):
        args = {
            'author': 'Rebecca De Mornay',
            'name': 'hw123'
        }
        expected = {
            'question_model': {
                'project_name': 'hw123',
                'author': 'Rebecca De Mornay',
            }
        }
        self._do_test_config_params(args, expected)

    def _do_test_config_params(self, _main_kwargs: dict, expected_config: dict):
        with tempfile.TemporaryDirectory() as tempdir:
            proj_root = os.path.join(tempdir, 'my_homework_12')
            retcode = hwsuite.init._main(proj_root, **_main_kwargs)
            self.assertEqual(0, retcode)
            hwconfig_file = os.path.join(proj_root, hwsuite.CFG_FILENAME)
            with open(hwconfig_file, 'r') as ifile:
                config = json.load(ifile)
            self.assertDictEqual(expected_config, config)
            if 'name' in _main_kwargs:
                cmakelists_lines = [line.rstrip() for line in hwsuite.tests.read_file_lines(os.path.join(proj_root, "CMakeLists.txt"))]
                self.assertIn(f"project({_main_kwargs['name']})", cmakelists_lines)

