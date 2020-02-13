#!/usr/bin/env python3

import os
import subprocess
import tempfile
from unittest import TestCase
import hwsuite.tests
from hwsuite import init
from hwsuite import question
import logging

from hwsuite.build import Builder

_log = logging.getLogger(__name__)


class BuilderTest(TestCase):

    def test_build(self):
        with tempfile.TemporaryDirectory() as tempdir:
            init.do_init(tempdir, 'build_unit', safety_mode='cautious')
            question.create(question.Questioner(tempdir), 'q1', 'safe')
            q1_dir = os.path.join(tempdir, 'q1')
            cfg = hwsuite.tests.get_config()
            builder = Builder.from_config(cfg)
            build_dir = os.path.join(q1_dir, 'cmake-build')
            builder.build(q1_dir, build_dir)
            executable = os.path.join(build_dir, 'q1')
            self.assertTrue(os.path.isfile(executable))
            completed = subprocess.run([executable])
            self.assertEqual(0, completed.returncode)