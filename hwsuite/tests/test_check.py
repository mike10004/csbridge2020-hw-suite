#!/usr/bin/env python3
import glob
import os
import sys
import tempfile
from typing import List
from unittest import TestCase
from pathlib import Path
from hwsuite import check
import logging
import argparse


_log = logging.getLogger(__name__)

def _create_namespace(**kwargs) -> argparse.Namespace:
    check_args = argparse.Namespace(subdirs=[], pause=check._DEFAULT_PAUSE_DURATION_SECONDS,
                           max_cases=None, threads=4, log_input=False, filter=None, report='none',
                           stuff='auto', test_cases='auto', project_dir=None)
    for k, v in kwargs.items():
        check_args.__setattr__(k, v)
    return check_args


class TestCaseRunnerTest(TestCase):

    def test__read_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            env_file = os.path.join(tempdir, 'env.txt')
            with open(env_file, 'w') as ofile:
                ofile.write("""\
foo=bar
haw
jek=
dee=cee=gur
baz=gaw""")
            env = check._read_env(env_file)
            expected = {
                'foo': 'bar',
                'haw': '',
                'jek': '',
                'dee': 'cee=gur',
                'baz': 'gaw',
            }
            self.assertDictEqual(expected, env)

    def test_run_test_case(self):
        t = check.TestCaseRunner('xargs', args=['-n1', 'echo', 'foo'])
        with tempfile.TemporaryDirectory() as tempdir:
            input_file = os.path.join(tempdir, 'input.txt')
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(input_file, 'w') as ofile:
                ofile.write("1\n2\n")
            with open(expected_file, 'w') as ofile:
                ofile.write("1\nfoo 1\n2\nfoo 2\n")
            outcome = t.run_test_case(input_file, expected_file)
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_run_test_case_no_input(self):
        with tempfile.TemporaryDirectory() as tempdir:
            any_file = os.path.join(tempdir, 'text.txt')
            with open(any_file, 'w') as ofile:
                ofile.write("This is my story\n")
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(expected_file, 'w') as ofile:
                ofile.write("This is my story\n")
            t = check.TestCaseRunner('cat', args=[any_file])
            outcome = t.run_test_case(None, expected_file)
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_run_test_case_tabs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            any_file = os.path.join(tempdir, 'text.txt')
            cat_text = "A\tB\tC\n"
            with open(any_file, 'w') as ofile:
                ofile.write(cat_text)
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(expected_file, 'w') as ofile:
                ofile.write(cat_text)
            t = check.TestCaseRunner('cat', args=[any_file])
            outcome = t.run_test_case(None, expected_file)
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_run_test_case_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(expected_file, 'w') as ofile:
                ofile.write("bar\n")
            t = check.TestCaseRunner('bash', args=['-c', 'echo $FOO'])
            outcome = t.run_test_case(None, expected_file, {'FOO': 'bar'})
        print(outcome)
        self.assertTrue(outcome.passed)

    def test__derive_counterparts(self):
        test_cases = [
            ('/path/to/dir/expected-outputABC.txt', 'inputABC.txt', 'envABC.txt'),
            ('/path/to/dir/expected-output-ABC.txt', 'input-ABC.txt', 'env-ABC.txt'),
            ('/path/to/dir/expected-output01.txt', 'input01.txt', 'env01.txt'),
            ('/path/to/dir/1-expected.txt', '1-input.txt', '1-env.txt'),
            ('/path/to/dir/def-expected-output.txt', 'def-input.txt', 'def-env.txt'),
        ]
        for argpath, inbase, envbase in test_cases:
            with self.subTest():
                actual = check._derive_counterparts(argpath, True)
                self.assertTupleEqual((inbase, envbase), actual)
