#!/usr/bin/env python3
import argparse
import logging
import os
import tempfile
import threading
from unittest import TestCase
from hwsuite import check
import hwsuite.tests
from hwsuite.check import StuffConfig, Throttle, ConcurrencyManager, TestCaseRunner, TestCaseOutcome

hwsuite.tests.configure_logging()

_log = logging.getLogger(__name__)


def _create_namespace(**kwargs) -> argparse.Namespace:
    # noinspection PyProtectedMember
    check_args = argparse.Namespace(subdirs=[], pause=check._DEFAULT_PAUSE_DURATION_SECONDS,
                           max_cases=None, threads=4, log_input=False, filter=None, report='none',
                           stuff='auto', test_cases='auto', project_dir=None, await=False)
    for k, v in kwargs.items():
        check_args.__setattr__(k, v)
    return check_args


def screen_factory() -> hwsuite.check.ScreenRunnableFactory:
    cfg = hwsuite.tests.get_config()
    return hwsuite.check.ScreenRunnableFactory(cfg)


class ModuleTest(TestCase):

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

    def test__spaces_to_tabs(self):
        for text, expected in [
            ("a  b", "a\tb"),
            ("a   b", "a\tb"),
            ("a                           b", "a\tb"),
            ("a\tb", "a\tb"),
            ("a b", "a b"),
            ("a b   c", "a b\tc"),
        ]:
            with self.subTest():
                actual = check._spaces_to_tabs(text)
                self.assertEqual(expected, actual, f"wrong result on input {repr(text)}")

    def test__derive_counterparts(self):
        test_cases = [
            ('/path/to/dir/expected-outputABC.txt', 'inputABC.txt', 'envABC.txt', 'argsABC.txt'),
            ('/path/to/dir/expected-output-ABC.txt', 'input-ABC.txt', 'env-ABC.txt', 'args-ABC.txt'),
            ('/path/to/dir/expected-output01.txt', 'input01.txt', 'env01.txt', 'args01.txt'),
            ('/path/to/dir/1-expected.txt', '1-input.txt', '1-env.txt', '1-args.txt'),
            ('/path/to/dir/def-expected-output.txt', 'def-input.txt', 'def-env.txt', 'def-args.txt'),
        ]
        for argpath, inbase, envbase, argsbase in test_cases:
            with self.subTest():
                actual = check._derive_counterparts(argpath, True)
                self.assertTupleEqual((inbase, envbase, argsbase), actual)


class UnitTestConcurrencyManager(ConcurrencyManager):

    def _run_test_case(self, test_case: TestCase) -> TestCaseOutcome:
        return TestCaseOutcome(True, 'true', test_case, 'hello, world', 'hello, world', 'fake')  # fabricate outcome


class ConcurrencyManagerTest(TestCase):

    def test_perform(self):
        mgr = UnitTestConcurrencyManager(TestCaseRunner('true', Throttle.default(), StuffConfig.default(), screen_factory()), 4)
        sample_cases = [
            check.TestCase.create('foo', 'bar'),
            check.TestCase.create('baz', 'gaw'),
            check.TestCase.create('gee', 'hab'),
            check.TestCase.create('har', 'jeb'),
            check.TestCase.create('kee', 'koh'),
            check.TestCase.create('lun', 'lum'),
        ]
        outcomes = {}
        for test_case in sample_cases:
            mgr.perform(test_case, outcomes)
        self.assertEqual(len(sample_cases), len(outcomes))
        for outcome in outcomes.values():
            self.assertEqual('fake', outcome.message)

class TestCaseRunnerTest(TestCase):

    def test_run_test_case_pass(self):
        t = check.TestCaseRunner('xargs', Throttle.default(), StuffConfig('auto', True), screen_factory())
        with tempfile.TemporaryDirectory() as tempdir:
            input_file = os.path.join(tempdir, 'input.txt')
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(input_file, 'w') as ofile:
                ofile.write("1\n2\n")
            with open(expected_file, 'w') as ofile:
                ofile.write("1\nfoo 1\n2\nfoo 2\n")
            outcome = t.run_test_case(check.TestCase.create(input_file, expected_file, args=['-n1', 'echo', 'foo']))
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_run_test_case_no_input_pass(self):
        outcome = self._do_test_run_test_case_no_input("This is my story\n", "This is my story\n")
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_run_test_case_no_input_fail(self):
        outcome = self._do_test_run_test_case_no_input("This is my story\n", "This is not my story\n")
        print(outcome)
        self.assertFalse(outcome.passed)

    # noinspection PyMethodMayBeStatic
    def _do_test_run_test_case_no_input(self, input_text, expected_text) -> check.TestCaseOutcome:
        with tempfile.TemporaryDirectory() as tempdir:
            any_file = os.path.join(tempdir, 'text.txt')
            with open(any_file, 'w') as ofile:
                ofile.write(input_text)
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(expected_file, 'w') as ofile:
                ofile.write(expected_text)
            t = check.TestCaseRunner('cat', Throttle.default(), StuffConfig.default(), screen_factory())
            return t.run_test_case(check.TestCase.create(None, expected_file, args=[any_file]))

    def test_run_test_case_tabs(self):
        cat_text = "A\tB\tC\n"
        outcome = self._do_test_run_test_case_no_input(cat_text, cat_text)
        self.assertTrue(outcome.passed)

    def test_run_test_case_tabs_fail(self):
        cat_text = "A\tB\tC\n"
        bad_text = "A\tC\tB\n"
        outcome = self._do_test_run_test_case_no_input(cat_text, bad_text)
        self.assertFalse(outcome.passed)

    def test_run_test_case_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(expected_file, 'w') as ofile:
                ofile.write("bar\n")
            t = check.TestCaseRunner('bash', Throttle.default(), StuffConfig.default(), screen_factory())
            outcome = t.run_test_case(check.TestCase.create(None, expected_file, {'FOO': 'bar'}, ['-c', 'echo $FOO']))
        print(outcome)
        self.assertTrue(outcome.passed)

