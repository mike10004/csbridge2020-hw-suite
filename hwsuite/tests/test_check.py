#!/usr/bin/env python3
import argparse
import logging
import os
import tempfile
from pathlib import Path
from typing import Sequence, List, Dict
from unittest import TestCase
from hwsuite import check
import hwsuite.init
import hwsuite.question
import hwsuite.build
import hwsuite.tests
from hwsuite.check import StuffConfig, Throttle, ConcurrencyManager, TestCaseRunner, TestCaseOutcome, CppChecker
from hwsuite.check import TestCaseRunnerFactory, TestCasesConfig, ValgrindConfig, Result, ScreenRunnable

hwsuite.tests.configure_logging()

_log = logging.getLogger(__name__)


def _create_namespace(**kwargs) -> argparse.Namespace:
    # noinspection PyProtectedMember
    check_args = argparse.Namespace(subdirs=[], pause=check._DEFAULT_PAUSE_DURATION_SECONDS,
                           max_cases=None, threads=4, log_input=False, filter=None, report='none',
                           stuff='auto', test_cases='auto', project_dir=None, await=False, require_screen='auto', valgrind=None)
    for k, v in kwargs.items():
        check_args.__setattr__(k, v)
    return check_args


class ModuleTest(TestCase):

    def test_detect_test_case_files(self):
        with tempfile.TemporaryDirectory() as proj_root:
            q_dir = os.path.join(proj_root, 'q3')
            os.makedirs(q_dir)
            expected_file = os.path.join(q_dir, 'expected.txt')
            with open(expected_file, 'wb') as ofile:
                ofile.write(b'')
            test_cases = check.detect_test_case_files(q_dir)
            self.assertEqual(1, len(test_cases))
            test_case = test_cases[0]
            self.assertEqual(expected_file, test_case.expected_file)
            self.assertIsNone(test_case.input_file)
            self.assertIsNone(test_case.env)
            self.assertTupleEqual(tuple(), test_case.args)

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

    def test__transform_expected(self):
        text = "a\tb"
        runner = TestCaseRunner('false', Throttle.default(), StuffConfig.default())
        actuals = runner._transform_expected(text, "whatever")
        actuals = list(actuals)
        self.assertListEqual([text, "a       b"], actuals)

    def test__check_tabs(self):
        expected_text = """\
Please enter a line of text:
  x  * 
1\twords
1\tx
"""
        actual_text = """\
Please enter a line of text:
  x  * 
1       words
1       x
"""
        runner = TestCaseRunner('false', Throttle.default(), StuffConfig.default())
        def to_outcome(a, b, c, d):
            return TestCaseOutcome(a, 'false', hwsuite.check.TestCase.create(None, 'x'), b, c, d)
        outcome = runner._check(Result(0, expected_text), Result(0, actual_text), to_outcome)
        self.assertTrue(outcome.passed, f"expect passed for {outcome}")

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
        mgr = UnitTestConcurrencyManager(TestCaseRunner('true', Throttle.default(), StuffConfig.default()), 4)
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
        t = check.TestCaseRunner('xargs', Throttle.default(), StuffConfig('auto', True))
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
    def _do_test_run_test_case_no_input(self, cat_text, expected_text) -> check.TestCaseOutcome:
        with tempfile.TemporaryDirectory() as tempdir:
            any_file = os.path.join(tempdir, 'text.txt')
            with open(any_file, 'w') as ofile:
                ofile.write(cat_text)
            expected_file = os.path.join(tempdir, 'expected.txt')
            with open(expected_file, 'w') as ofile:
                ofile.write(expected_text)
            t = check.TestCaseRunner('cat', Throttle.default(), StuffConfig.default())
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
            hwsuite.tests.write_text_file("bar\n", expected_file)
            t = check.TestCaseRunner('bash', Throttle.default(), StuffConfig.default())
            outcome = t.run_test_case(check.TestCase.create(None, expected_file, {'FOO': 'bar'}, ['-c', 'echo $FOO']))
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_run_test_case_no_expected(self):
        t = check.TestCaseRunner('true', Throttle.default(), StuffConfig.default())
        outcome = t.run_test_case(check.TestCase.create(None, None))
        print(outcome)
        self.assertTrue(outcome.passed)

    def test_screen_stuff_special_chars(self):
        outcome = self.do_test_screen_stuff_special_chars(StuffConfig('auto', True))
        print(outcome)
        self.assertTrue(outcome.passed, f"did not pass: {outcome}")

    def test_screen_stuff_special_chars_strict_fail(self):
        try:
            self.do_test_screen_stuff_special_chars(StuffConfig('strict', True))
            self.fail("should have thrown exception")
        except hwsuite.check.StuffContentException:
            pass

    # noinspection PyMethodMayBeStatic
    def do_test_screen_stuff_special_chars(self, stuff_config: StuffConfig) -> TestCaseOutcome:
        assert stuff_config.eof, "StuffConfig.eof must be True because `cat` likes it"
        with tempfile.TemporaryDirectory() as tempdir:
            input_file = os.path.join(tempdir, 'input.txt')
            text = "caret ^ hash # money $ cool\n"
            hwsuite.tests.write_text_file(text, input_file)
            expected_file = os.path.join(tempdir, 'expected.txt')
            hwsuite.tests.write_text_file(text + text, expected_file)  # text+text because once on stdin, once on stdout
            t = check.TestCaseRunner('cat', Throttle.default(), stuff_config)
            outcome = t.run_test_case(check.TestCase.create(input_file, expected_file))
            return outcome


class FixedTestCaseFilesChecker(CppChecker):

    def __init__(self, runner_factory: TestCaseRunnerFactory, concurrency_level: int, test_case_files: Sequence[TestCase]):
        super().__init__(runner_factory, concurrency_level)
        self.test_cases = list(test_case_files)

    def _detect_test_cases(self, q_dir: str=None) -> List[TestCase]:
        assert self.test_cases, "this method must return nonempty"
        return self.test_cases


class CppCheckerTest(TestCase):

    def test_zero_test_case_files(self):
        runner_factory = TestCaseRunnerFactory(Throttle.default(), StuffConfig.default())
        checker = CppChecker(runner_factory, 1)
        with tempfile.TemporaryDirectory() as proj_dir:
            q_dir = os.path.join(proj_dir, 'q14')
            os.makedirs(q_dir)
            Path(os.path.join(q_dir, "main.cpp")).touch()
            detected = checker._detect_test_cases(q_dir)
        self.assertEqual(1, len(detected), "zero test case files should yield exactly one standard test case")
        test_case = list(detected)[0]
        self.assertIsNone(test_case.input_file, "input")
        self.assertIsNone(test_case.expected_file, "expected")
        self.assertEqual(0, test_case.exit_code, "exit code")

    def test_valgrind_error(self):
        with tempfile.TemporaryDirectory() as proj_dir:
            hwsuite.init.do_init(proj_dir, hwsuite.init._DEFAULT_SAFETY_MODE, {})
            q_dir = hwsuite.question._main_raw(proj_dir, 'q1', excludes='question,testcases')
            cpp_file = os.path.join(q_dir, 'main.cpp')
            hwsuite.tests.write_text_file("""\
            #include <iostream>
            int main() {
                int* a = new int[3];
                a[0] = 1;
                a[1] = 2;
                a[2] = 3;
                std::cout << a[0] << a[1] << a[2] << std::endl;
                return 0;
            }
            """, cpp_file)
            hwsuite.tests.write_text_file("""\
123
""", os.path.join(q_dir, '1-expected.txt'))
            hwsuite.build.build(proj_dir)
            args = argparse.Namespace(valgrind='applicability=auto&verbosity=quiet')
            valgrind_config = ValgrindConfig.from_options(args)
            runner_factory = TestCaseRunnerFactory(Throttle.default(), StuffConfig.default(), valgrind_config=valgrind_config)
            checker = CppChecker(runner_factory, 1)
            outcomes: Dict[TestCase, TestCaseOutcome] = checker.check_cpp(cpp_file, TestCasesConfig(1, None))
            self.assertIsNotNone(outcomes)
            self.assertIsInstance(outcomes, dict)
            self.assertEqual(1, len(outcomes))
            outcome = list(outcomes.values())[0]
            self.assertFalse(outcome.passed, "expect failed memcheck")
            self.assertTrue(outcome.message.startswith("memcheck"), "expect message includes 'memcheck'")

    def test_dont_stuff_if_terminated(self):
        with tempfile.TemporaryDirectory() as proj_dir:
            hwsuite.init.do_init(proj_dir, hwsuite.init._DEFAULT_SAFETY_MODE, {})
            q_dir = hwsuite.question._main_raw(proj_dir, 'q2', excludes='question,testcases')
            cpp_file = os.path.join(q_dir, 'main.cpp')
            hwsuite.tests.write_text_file("""\
            #include <iostream>
            #include <cassert>
            using namespace std;
            int main() {
                char ch;
                cin >> ch;
                assert(ch == 'a');
                cin >> ch;
                assert(ch == 'b');
                cin >> ch;
                assert(ch == 'c');
                return 0;
            }
            """, cpp_file)
            hwsuite.tests.write_text_file("a\nz\nc\n", os.path.join(q_dir, '1-input.txt'))
            hwsuite.tests.write_text_file('', os.path.join(q_dir, '1-expected.txt'))
            hwsuite.build.build(proj_dir)
            screen_runnables = []
            class CustomTestCaseRunnerFactory(TestCaseRunnerFactory):

                def __init__(self, throttle: Throttle, stuff_config: StuffConfig):
                    super().__init__(throttle, stuff_config)

                def create(self, executable: str):
                    runner = super().create(executable)
                    def _runner(procdef):
                        runnable = ScreenRunnable(procdef)
                        screen_runnables.append(runnable)
                        return runnable
                    runner.screen_runnable_factory = _runner
                    return runner

            runner_factory = CustomTestCaseRunnerFactory(Throttle.default(), StuffConfig.default())
            checker = CppChecker(runner_factory, 1)
            outcomes: Dict[TestCase, TestCaseOutcome] = checker.check_cpp(cpp_file, TestCasesConfig(1, None))
            self.assertEqual(1, len(screen_runnables))
            screen_runnable = screen_runnables[0]
            self.assertEqual(1, screen_runnable.num_stuffs, "num stuffs by ScreenRunnable")
            self.assertIsNotNone(outcomes)
            self.assertIsInstance(outcomes, dict)
            self.assertEqual(1, len(outcomes))
            outcome = list(outcomes.values())[0]


