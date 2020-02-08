#!/usr/bin/env python3

"""
    check.py builds the executables and then runs the test cases.
    
    Your system must have `screen` installed.
"""
import argparse
import difflib
import fnmatch
import re
import sys
import logging
import threading
import uuid
import tempfile
import os.path
import subprocess
import time
from hwsuite import testcases
from subprocess import PIPE, DEVNULL
from argparse import ArgumentParser
from typing import List, Tuple, Optional, NamedTuple, Dict, FrozenSet, Generator, Callable
from hwsuite import _cmd
import hwsuite.build


_log = logging.getLogger(__name__)
_DEFAULT_PAUSE_DURATION_SECONDS = 0.5
_REPORT_CHOICES = ('diff', 'full', 'repr', 'none')
_TEST_CASES_CHOICES = ('auto', 'require', 'existing')


def read_file_text(pathname: str, ignore_failure=False) -> str:
    try:
        with open(pathname, 'r') as ifile:
            return ifile.read()
    except IOError:
        if not ignore_failure:
            raise


def read_file_lines(pathname: str) -> List[str]:
    with open(pathname, 'r') as ifile:
        return [line for line in ifile]


class TestCase(NamedTuple):

    input_file: Optional[str]
    expected_file: str
    env: Optional[FrozenSet[Tuple[str, str]]]

    def env_dict(self) -> Optional[Dict[str, str]]:
        return None if self.env is None else dict(self.env)

    @staticmethod
    def create(input_file: Optional[str], expected_file: str, env: Optional[Dict[str, str]]=None):
        env = None if env is None else frozenset(env.items())
        return TestCase(input_file, expected_file, env)


def _read_env(env_file) -> Dict[str, str]:
    env = {}
    with open(env_file, 'r') as ifile:
        for line in ifile:
            line = line.strip("\r\n")
            parts = line.split("=", 1)
            if len(parts) > 1:
                env[parts[0]] = parts[1]
            elif len(parts) > 0 and parts[0]:
                env[parts[0]] = ''
    return env


def _derive_counterparts(expected_pathname, suppress_deprecation=False) -> Tuple[str, str]:
    """Returns a tuple of basenames of the input and env file counterparts to the given expected output file pathname."""
    basename = os.path.basename(expected_pathname)
    def _derive(token, suffix):
        if suffix:
            identifier = basename[:len(basename) - len(token)]
            return identifier + '-input.txt', identifier + '-env.txt'
        else:
            identifier = basename[len(token):]
            return 'input' + identifier, 'env' + identifier
    if basename.endswith("-expected.txt"):
        return _derive("-expected.txt", True)
    elif basename.endswith("-expected-output.txt", True):
        return _derive("-expected-output.txt", True)
    elif basename.startswith("expected-output"):
        if not suppress_deprecation:
            _log.warning("use of prefix 'expected-output' is deprecated: %s; use suffix -expected.txt instead", basename)
        return _derive("expected-output", False)
    raise ValueError("basename pattern not recognized; should be something like *-input.txt or *-expected.txt")


def _create_test_case(expected_pathname: str) -> TestCase:
    basename = os.path.basename(expected_pathname)
    input_basename, env_basename = _derive_counterparts(basename)
    parent = os.path.dirname(expected_pathname)
    input_file = os.path.join(parent, input_basename)
    env_file = os.path.join(parent, env_basename)
    if not os.path.exists(input_file):
        input_file = None
    env = None
    if os.path.exists(env_file):
        env = frozenset(_read_env(env_file).items())
    return TestCase(input_file, expected_pathname, env)


def detect_test_case_files(q_dir: str) -> List[TestCase]:
    test_cases = []
    for root, dirs, files in os.walk(q_dir):
        for f in files:
            if f.startswith('expected-output') or f.endswith('-expected.txt') or f.endswith('-expected-output.txt'):
                test_case = _create_test_case(os.path.join(root, f))
                test_cases.append(test_case)
    if not test_cases:
        expected_file = os.path.join(q_dir, 'expected-output.txt')
        if os.path.isfile(expected_file):
            return [TestCase(None, expected_file, None)]
        return []
    return sorted(test_cases)


class TestCaseOutcome(NamedTuple):

    passed: bool
    executable: str
    test_case: TestCase
    expected_text: str
    actual_text: str
    message: str


def _spaces_to_tabs(text: str) -> str:
    """Replace sequences of multiple spaces with a single tab character."""
    return re.sub(r' {2,}', "\t", text)


# noinspection PyMethodMayBeStatic
class TestCaseRunner(object):

    def __init__(self, executable, pause_duration=_DEFAULT_PAUSE_DURATION_SECONDS, log_input=False, stuff_mode='auto', args=None):
        self.executable = executable
        self.pause_duration = pause_duration
        self.log_input = log_input
        self.stuff_mode = stuff_mode
        self.args = args
        self.skip_screen_if_no_input = False
        self.strict_check = False

    def _pause(self, duration=None):
        time.sleep(self.pause_duration if duration is None else duration)

    def _prepare_stuff(self, line):
        if self.stuff_mode == 'auto' and line[-1] != "\n":
            line += "\n"
        return line

    def _transform_screenlog(self, actual_text: str, expected_text: str) -> Generator[str, None, None]:
        """Transforms screenlog text into multiple strings suitable for comparison to expected text.

        We always return the original text unchanged as the first element of the returned list.
        If the expected text has certain characteristics, then additional candidate strings may
        be appended to the list.

        One problem we encounter is a Screen bug wherein tabs are printed as spaces to screenlog.
        See https://serverfault.com/a/278051. To handle that case, if the expected text contains
        tabs, then a transform is applied the actual text wherein """
        yield actual_text
        if "\t" in expected_text:
            yield _spaces_to_tabs(actual_text)

    def _compare_texts(self, expected, actual) -> bool:
        return expected == actual

    def _check(self, expected_text: str, actual_text: str, to_outcome: Callable[[bool, str, str, str], TestCaseOutcome]) -> TestCaseOutcome:
        expected_texts = [expected_text]
        if not self.strict_check and "\t" in expected_text:
            # TODO determine whether there's a way to modify the expected text for comparison
            pass
        for candidate in self._transform_screenlog(actual_text, expected_text):
            for expected_text_ in expected_texts:
                if self._compare_texts(candidate, expected_text_):
                    return to_outcome(True, expected_text_, actual_text, "ok")
        return to_outcome(False, expected_text, actual_text, "diff")

    def run_test_case(self, test_case: TestCase) -> TestCaseOutcome:
        input_file = test_case.input_file
        expected_file = test_case.expected_file
        env = test_case.env_dict()

        tid = threading.current_thread().ident
        expected_text = read_file_text(expected_file)

        def make_outcome(passed: bool, expected_text_: str, actual_text: Optional[str], message: str) -> TestCaseOutcome:
            return TestCaseOutcome(passed, self.executable, test_case, expected_text_, actual_text, message)

        def check(actual_text: str) -> TestCaseOutcome:
            return self._check(expected_text, actual_text, make_outcome)

        if input_file is None and self.skip_screen_if_no_input:
            output = _cmd([self.executable] + (self.args or []))
            return check(output)

        if input_file is None:
            input_lines = []
        else:
            input_lines = read_file_lines(input_file)
        case_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tempdir:
            cmd = ['screen', '-L', '-S', case_id, '-d', '-m', '--', self.executable]
            if self.args:
                cmd += self.args
            exitcode = subprocess.call(cmd, env=env, cwd=tempdir)
            if exitcode != 0:
                return make_outcome(False, expected_text, None, f"screen start failure {exitcode}")
            _log.debug("[%s] screen session %s started for %s; feeding lines from %s", tid, case_id, os.path.basename(self.executable), None if input_file is None else os.path.basename(input_file))
            completed = False
            try:
                screenlog = os.path.join(tempdir, 'screenlog.0')
                for i, line in enumerate(input_lines):
                    self._pause()
                    line = self._prepare_stuff(line)
                    if self.log_input: _log.debug("[%s] feeding line %s to process: %s", tid, i+1, repr(line))
                    proc = subprocess.run(['screen', '-S', case_id, '-X', 'stuff', line], stdout=PIPE, stderr=PIPE)  # note: important that line has terminal newline char
                    if proc.returncode != 0:
                        stdout, stderr = proc.stdout.decode('utf8'), proc.stderr.decode('utf8')
                        msg = f"[{tid}] stuff exit code {proc.returncode} feeding line {i+1}; stderr={stderr}; stdout={stdout}"
                        _log.debug(msg)
                        return make_outcome(False, expected_text, read_file_text(screenlog, True), msg)
                completed = True
                # TODO: reattach to session and wait for termination (with a timeout)
            finally:
                self._pause()  ## allow process to exit cleanly
                exitcode = subprocess.call(['screen', '-S', case_id, '-X', 'quit'], stdout=DEVNULL, stderr=DEVNULL)  # ok if failed; probably already terminated
                if not completed and exitcode != 0:
                    _log.warning("screen 'quit' failed with code %s", exitcode)
            output = read_file_text(screenlog).replace("\r\n", "\n")
        return check(output)



class ConcurrencyManager(object):
    
    def __init__(self, runner: TestCaseRunner, concurrency_level: int, q_name, outcomes):
        self.concurrer = threading.Semaphore(concurrency_level)
        self.runner = runner
        self.q_name = q_name
        self.outcomes = outcomes
        self.outcomes_lock = threading.Lock()

    def perform(self, test_case: TestCase, i):
        input_file, expected_file, env = test_case
        self.concurrer.acquire()
        try:
            outcome = self.runner.run_test_case(test_case)
            input_name = os.path.basename(input_file)
            if outcome.passed:
                _log.debug("%s: case %s (%s) passed", self.q_name, i + 1, input_name)
            else:
                _log.info("%s: case %s (%s) failed: %s", self.q_name, i + 1, input_name, outcome.message)
        finally:
            self.concurrer.release()
        self.outcomes_lock.acquire()
        try:
            self.outcomes[test_case] = outcome
        finally:
            self.outcomes_lock.release()


def report(outcomes: List[TestCaseOutcome], report_type: str, ofile=sys.stderr):
    for outcome in outcomes:
        q_name = os.path.basename(outcome.executable)
        input_name = os.path.basename(outcome.test_case.input_file)
        print(f"{q_name}: {input_name}: {outcome.message}")
        if outcome.message == 'diff':
            if report_type == 'diff':
                expected = outcome.expected_text.split("\n")
                actual = outcome.actual_text.split("\n")
                delta = difflib.context_diff(expected, actual)
                for line in delta:
                    print(line, file=ofile)
            elif report_type == 'full':
                print("=================================================", file=ofile)
                print("EXPECTED", file=ofile)
                print("=================================================", file=ofile)
                print(outcome.expected_text, end="", file=ofile)
                print("=================================================", file=ofile)
                print("=================================================", file=ofile)
                print("ACTUAL", file=ofile)
                print("=================================================", file=ofile)
                print(outcome.actual_text, end="", file=ofile)
                print("=================================================", file=ofile)
            elif report_type == 'repr':
                print("expected: {}".format(repr(outcome.expected_text)), file=ofile)
                print("  actual: {}".format(repr(outcome.actual_text)), file=ofile)
            else:
                _log.debug("test case failure reported with message=diff but diff_action=%s", report_type)


def matches(filter_pattern: Optional[str], test_case: Tuple[Optional[str], str]):
    if filter_pattern is None:
        return True
    filename = os.path.basename(test_case[0])
    return fnmatch.fnmatch(filename, filter_pattern)


def check_cpp(cpp_file: str, concurrency_level: int, pause_duration: float, max_test_cases:int, log_input: bool, 
              filter_pattern: str, report_type: str, stuff_mode: str):
    q_dir = os.path.dirname(cpp_file)
    q_name = os.path.basename(q_dir)
    q_executable = os.path.join(q_dir, 'cmake-build', q_name)
    assert os.path.isfile(q_executable), "not found: " + q_executable
    test_case_files = detect_test_case_files(q_dir)
    _log.info("%s: detected %s test cases", q_name, len(test_case_files))
    if not test_case_files:
        return
    runner = TestCaseRunner(q_executable, pause_duration, log_input, stuff_mode)
    outcomes = {}
    threads: List[threading.Thread] = []
    concurrency_mgr = ConcurrencyManager(runner, concurrency_level, q_name, outcomes)
    for i, test_case in enumerate(test_case_files):
        if max_test_cases is not None and i >= max_test_cases:
            _log.debug("breaking early due to test case limit")
            break
        if not matches(filter_pattern, test_case):
            _log.debug("skipping; filter %s rejected test case %s", filter_pattern, test_case)
            continue
        t = threading.Thread(target=lambda: concurrency_mgr.perform(test_case, i))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    if not threads:
        _log.warning("all test cases were skipped")
    failures = [outcome for outcome in outcomes.values() if not outcome.passed]
    if failures:
        _log.info("%s: %s failures among %s test cases", q_name, len(failures), len(outcomes))
    elif len(outcomes) > 0:
        _log.info("%s: all %s tests pass", q_name, len(outcomes))
    report(failures, report_type)


def _main(args: argparse.Namespace):
    proj_dir = os.path.abspath(args.project_dir or hwsuite.find_proj_root())
    _log.debug("this project dir is %s (specified %s)", proj_dir, args.project_dir)
    assert proj_dir and os.path.isdir(proj_dir), "failed to detect project directory"
    _log.debug("building executables by running build in %s", proj_dir)
    hwsuite.build.build(proj_dir)
    main_cpps = []
    if args.subdirs:
        _log.debug("limiting tests to subdirectories: %s", args.subdirs)
        main_cpps += [os.path.join(proj_dir, subdir, 'main.cpp') for subdir in args.subdirs]
    else:
        _log.debug("searching %s for main.cpp files", proj_dir)
        for root, dirs, files in os.walk(proj_dir):
            for f in files:
                if f == 'main.cpp' and not os.path.exists(os.path.join(root, '.nocheck')):
                    main_cpps.append(os.path.join(root, f))
    if not main_cpps:
        _log.error("no main.cpp files found")
        return 1
    for i, cpp_file in enumerate(sorted(main_cpps)):
        if args.test_cases != 'existing':
            defs_file = os.path.join(os.path.dirname(cpp_file), 'test-cases.json')
            if not os.path.isfile(defs_file):
                if args.test_cases == 'require':
                    raise FileNotFoundError(defs_file)
            else:
                testcases.produce_from_defs(defs_file)
        check_cpp(cpp_file, args.threads, args.pause, args.max_cases, args.log_input, args.filter, args.report, args.stuff)
    return 0


def main():
    parser = ArgumentParser()
    parser.add_argument("subdirs", nargs='*', help="subdirectories containing executables to test; if none specified, run all")
    hwsuite.add_logging_options(parser)
    parser.add_argument("-p", "--pause", type=float, metavar="DURATION", help="pause duration (seconds)", default=_DEFAULT_PAUSE_DURATION_SECONDS)
    parser.add_argument("-m", "--max-cases", type=int, default=None, metavar="N", help="run at most N test cases per cpp")
    parser.add_argument("-j", "-t", "--threads", type=int, default=4, metavar="N", help="concurrency level for test cases")
    parser.add_argument("--log-input", help="log feeding of input lines at DEBUG level")
    parser.add_argument("--filter", metavar="PATTERN", help="match test case input filenames against PATTERN")
    parser.add_argument("--report", metavar="ACTION", choices=_REPORT_CHOICES, default='diff', help=f"what to print on test case failure; one of {_REPORT_CHOICES}; default is 'diff'")
    parser.add_argument("--stuff", metavar="MODE", choices=('auto', 'strict'), default='auto', help="how to interpret input lines sent to process via `screen -X stuff`: 'auto' or 'strict'")
    parser.add_argument("--test-cases", metavar="MODE", choices=_TEST_CASES_CHOICES, help=f"test case generation mode; choices are {_TEST_CASES_CHOICES}; default 'auto' means attempt to re-generate")
    parser.add_argument("--project-dir", metavar="DIR", help="project directory (if not current directory)")
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    try:
        return _main(args)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
