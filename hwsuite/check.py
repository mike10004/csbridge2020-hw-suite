#!/usr/bin/env python3

"""
    check.py builds the executables and then runs the test cases.
    
    Your system must have `screen` installed.
"""
import argparse
import difflib
import fnmatch
import multiprocessing
import re
import sys
import logging
import threading
import traceback
import uuid
import tempfile
import os.path
import subprocess
import time
from hwsuite import testcases
from subprocess import PIPE, DEVNULL
from argparse import ArgumentParser
from typing import List, Tuple, Optional, NamedTuple, Dict, FrozenSet, Generator, Callable, Sequence
import hwsuite.build


_log = logging.getLogger(__name__)
_DEFAULT_PAUSE_DURATION_SECONDS = 0.5
_DEFAULT_PROCESSING_TIMEOUT_SECONDS = 5
_REPORT_CHOICES = ('diff', 'full', 'repr', 'none')
_TEST_CASES_CHOICES = ('auto', 'require', 'existing')
_ERR_TEST_CASE_FAILURES = 3
_STUFF_MODES = ('auto', 'strict')

def read_file_text(pathname: str, ignore_failure=False) -> Optional[str]:
    """Reads text from a file, possibly ignoring errors.
    Returns file text or None if failure did occur but was ignored.
    """
    try:
        with open(pathname, 'r') as ifile:
            return ifile.read()
    except IOError:
        if not ignore_failure:
            raise

def read_file_lines(pathname: str, rstrip=None) -> List[str]:
    def xform(line):
        return line if rstrip is None else line.rstrip(rstrip)
    with open(pathname, 'r') as ifile:
        return list(map(xform, ifile.readlines()))


class TestCase(NamedTuple):

    input_file: Optional[str]
    expected_file: str
    env: Optional[FrozenSet[Tuple[str, str]]]
    args: Tuple[str, ...]

    def env_dict(self) -> Optional[Dict[str, str]]:
        return None if self.env is None else dict(self.env)

    @staticmethod
    def create(input_file: Optional[str], expected_file: str, env: Optional[Dict[str, str]]=None, args: Optional[Sequence[str]]=None):
        env = None if env is None else frozenset(env.items())
        args = tuple() if args is None else tuple(args)
        return TestCase(input_file, expected_file, env, args)

    # noinspection PyMethodMayBeStatic
    def check_exit_code(self, exit_code: int) -> bool:
        """Return True iff the exit code is what is expected for this test case."""
        return exit_code == 0


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


def _derive_counterparts(expected_pathname, suppress_deprecation=False) -> Tuple[str, str, str]:
    """Returns a tuple of basenames of the input, env, and args file counterparts to the given expected output file pathname."""
    basename = os.path.basename(expected_pathname)
    def _derive(token, suffix):
        if suffix:
            identifier = basename[:len(basename) - len(token)]
            return identifier + '-input.txt', identifier + '-env.txt', identifier + '-args.txt'
        else:
            identifier = basename[len(token):]
            return 'input' + identifier, 'env' + identifier, 'args' + identifier
    if basename == 'expected.txt':
        return 'input.txt', 'env.txt', 'args.txt'
    elif basename.endswith("-expected.txt"):
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
    input_basename, env_basename, args_basename = _derive_counterparts(basename)
    parent = os.path.dirname(expected_pathname)
    input_file = os.path.join(parent, input_basename)
    env_file = os.path.join(parent, env_basename)
    args_file = os.path.join(parent, env_basename)
    if not os.path.exists(input_file):
        input_file = None
    env = None
    if os.path.exists(env_file):
        env = frozenset(_read_env(env_file).items())
    args = tuple()
    if os.path.exists(args_file):
        args = tuple(read_file_lines(args_file, rstrip="\n"))
    return TestCase(input_file, expected_pathname, env, args)


def detect_test_case_files(q_dir: str) -> List[TestCase]:
    test_cases = []
    for root, dirs, files in os.walk(q_dir):
        for f in files:
            if f.startswith('expected-output') or f.endswith('-expected.txt') or f.endswith('-expected-output.txt') or f == 'expected.txt':
                test_case = _create_test_case(os.path.join(root, f))
                test_cases.append(test_case)
    return sorted(test_cases)


class TestCaseOutcome(NamedTuple):

    passed: bool
    executable: str
    test_case: TestCase
    expected_text: str
    actual_text: str
    message: str


class ProcessDefinition(NamedTuple):

    executable: str
    args: Tuple[str, ...]
    cwd: Optional[str]
    env: Optional[Dict[str, str]]

    def to_cmd(self):
        return [self.executable] + list(self.args)


class ScreenStateException(Exception):
    pass


class PollConfig(NamedTuple):

    interval: float
    limit: int

    @staticmethod
    def disabled():
        return PollConfig(1.0, 0)

    @staticmethod
    def from_args_await(args: argparse.Namespace, limit: int=10) -> 'PollConfig':
        interval = get_arg(args, 'await', None)
        if interval is None:
            return PollConfig.disabled()
        return PollConfig(interval, limit)


class LogWatcher(object):

    def __init__(self, pathname: str, requirement:Optional[Callable]=None):
        self.pathname = pathname
        self.requirement = requirement

    def _satisfied(self, text):
        req = self.requirement or str.strip
        return req(text)

    def await_output(self, poll_config, on_timeout='return'):
        num_polls = 0
        text = None
        while num_polls < poll_config.limit:
            text = read_file_text(self.pathname, True) or ''
            if self._satisfied(text):
                return
            time.sleep(poll_config.interval)
            num_polls += 1
        if on_timeout == 'raise':
            raise TimeoutError()
        return text


def get_arg(args: argparse.Namespace, attr_name: str, default_value):
    try:
        return args.__getattr__(attr_name)
    except AttributeError:
        return default_value

_BAD_STUFF_CHARS = "^#"

class StuffContentException(ValueError):

    pass

class StuffConfig(NamedTuple):

    mode: str
    eof: bool

    def format_line(self, line: str) -> str:
        if not self.mode in _STUFF_MODES:
            raise ValueError("unrecognized stuff mode")
        if self.mode == 'strict':
            if StuffConfig.has_special_chars(line):
                raise StuffContentException(f"input line contains characters that may not be compatible with screen `stuff` command: {repr(line)} has at least one of {repr(_BAD_STUFF_CHARS)}")
        if self.mode == 'auto':
            line = StuffConfig.translate_special_chars(line)
            if line[-1] != "\n":
                line += "\n"
        return line

    @staticmethod
    def has_special_chars(line: str) -> bool:
        for ch in _BAD_STUFF_CHARS:
            if ch in line:
                return True
        return False

    @staticmethod
    def translate_special_chars(line: str) -> str:
        if not StuffConfig.has_special_chars(line):
            return line
        chars = list(line)
        for i, ch in enumerate(chars):
            if ch in _BAD_STUFF_CHARS:
                ch = "\\" + oct(ord(ch))[2:]
            chars[i] = ch
        return ''.join(chars)

    @staticmethod
    def default():
        return StuffConfig('auto', False)

    @staticmethod
    def from_args(args: argparse.Namespace):
        return StuffConfig(get_arg(args, 'stuff', 'auto'), get_arg(args, 'eof', False))


# noinspection PyMethodMayBeStatic
class ScreenRunnable(object):

    def __init__(self, procdef):
        self.procdef = procdef
        self.case_id = str(uuid.uuid4())
        self.started_proc: Optional[subprocess.Popen] = None
        self.completed_proc: Optional[subprocess.CompletedProcess] = None
        self.logfile = os.path.join(self.procdef.cwd, 'screenlog.0')

    def __str__(self):
        return f"ScreenRunnable<{self.procdef},launched={self.launched},finished={self.finished()}>"

    def launched(self):
        return not self.finished() and self.started_proc is not None

    def start(self):
        # TODO use -Logfile filename to make this more stable
        cmd = ['screen', '-L', '-S', self.case_id, '-D', '-m', '--'] + self.procdef.to_cmd()
        self.started_proc = subprocess.Popen(cmd, env=self.procdef.env, cwd=self.procdef.cwd, stdout=PIPE, stderr=PIPE)
        return self.started_proc

    def await_proc(self, timeout: float):
        try:
            self.started_proc.wait(timeout)
            self.completed_proc = subprocess.CompletedProcess(self.started_proc.args, self.started_proc.returncode, '', '')
            self.started_proc = None
            _log.debug("screen process completed with exit code %s", self.completed_proc.returncode)
        except subprocess.TimeoutExpired:
            _log.warning("process did not terminate before timeout of %s seconds elapsed", timeout)
            pass

    def stuff(self, line: str, cfg: StuffConfig, line_num: int=0) -> subprocess.CompletedProcess:
        """Sends a line of text to process standard input.
        This uses the screen command 'stuff'. The line number is used only for log messages."""
        if not self.launched() or self.finished():
            raise ScreenStateException(str(self))
        thread_id = threading.current_thread().ident
        # note: it is important for 'stuff' command that line has terminal newline char
        line = cfg.format_line(line)
        _log.debug("[%s] feeding line %s to process: %s", thread_id, line_num, repr(line))
        proc = subprocess.run(['screen', '-S', self.case_id, '-X', 'stuff', line], stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            stdout, stderr = proc.stdout.decode('utf8'), proc.stderr.decode('utf8')
            msg = f"[{thread_id}] stuff exit code {proc.returncode} feeding line {line_num}; stderr={stderr}; stdout={stdout}"
            _log.info(msg)
        return proc

    def stuff_eof(self) -> subprocess.CompletedProcess:
        proc = subprocess.run(['screen', '-S', self.case_id, '-X', 'stuff', "^D"], stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            _log.info("sending EOF to process failed with code %s", proc.returncode)
        return proc

    def finished(self):
        return self.completed_proc is not None

    def quit(self) -> bool:
        if not self.launched:
            return True
        if self.finished():
            return True
        _log.debug("quitting screen process")
        exitcode = subprocess.call(['screen', '-S', self.case_id, '-X', 'quit'], stdout=DEVNULL, stderr=DEVNULL)
        if not self.finished and exitcode != 0:  # there's a race here and we may not know the proc finished but it did and 'quit' returned error, but there are no ill effects and it's pretty rare
            _log.warning("screen 'quit' failed with code %s", exitcode)
        return exitcode == 0

    def kill(self):
        open_proc = self.started_proc
        if open_proc is None:
            _log.info("proc not retained; maybe already finished? self.finished=%s", self.finished())
            return
        _log.info("terminating process %s", open_proc.pid)
        open_proc.terminate()
        if open_proc.returncode is None:
            _log.warning("SIGTERM pid %s had no effect; trying SIGKILL", open_proc.pid)
            open_proc.kill()
        _log.info("after term/kill attempt, returncode = %s", open_proc.returncode)
        return open_proc.returncode

    def logfile_text(self, ignore_failure=False):
        return read_file_text(self.logfile, ignore_failure)


class Throttle(NamedTuple):

    pause_duration: float
    await: PollConfig
    processing_timeout: float

    @staticmethod
    def default():
        return Throttle(_DEFAULT_PAUSE_DURATION_SECONDS, PollConfig.disabled(), _DEFAULT_PROCESSING_TIMEOUT_SECONDS)


# noinspection PyMethodMayBeStatic
class TestCaseRunner(object):

    def __init__(self, executable, throttle: Throttle, stuff_config: StuffConfig, require_screen = 'auto'):
        self.executable = executable
        self.throttle = throttle
        assert isinstance(throttle, Throttle)
        self.stuff_config = stuff_config
        assert isinstance(stuff_config, StuffConfig)
        self.processing_timeout: float = 5.0
        self.require_screen = require_screen

    def _pause(self, duration=None):
        time.sleep(self.throttle.pause_duration if duration is None else duration)

    def _transform_expected(self, expected_text: str, actual_text: str) -> List[str]:
        """Transforms expected text into one or more strings suitable for comparison to actual text.

        We always return the original text unchanged as the first element of the returned list.
        If the expected or actual text has certain characteristics, then additional candidate strings may
        be appended to the list.

        One problem we encounter is a Screen bug wherein tabs are printed as spaces to screenlog.
        See https://serverfault.com/a/278051. To handle that case, if the expected text contains
        tabs, then a transform is applied to expand the tabs."""
        texts = [expected_text]
        if "\t" in expected_text:
            texts.append(expected_text.expandtabs(8))
        return texts

    def _transform_actual(self, expected_text: str, actual_text: str) -> List[str]:
        """Transforms screenlog text into one or more strings suitable for comparison to expected text.

        We always return the original text unchanged as the first element of the returned list.
        If the expected or actual text has certain characteristics, then additional candidate strings may
        be appended to the list.
        """
        return [actual_text]

    def _compare_texts(self, expected, actual) -> bool:
        return expected == actual

    def _check(self, expected_text: str, actual_text: str, to_outcome: Callable[[bool, str, str, str], TestCaseOutcome]) -> TestCaseOutcome:
        expected_texts = self._transform_expected(expected_text, actual_text)
        actual_texts = self._transform_actual(expected_text, actual_text)
        expected_candidate, actual_candidate = None, None
        num_comparisons = 0
        for expected_candidate in expected_texts:
            for actual_candidate in actual_texts:
                num_comparisons += 1
                if self._compare_texts(expected_candidate, actual_candidate):
                    return to_outcome(True, expected_text, actual_text, "ok")
        _log.debug("no equal texts after %s comparisons", num_comparisons)
        assert num_comparisons > 0, "BUG: expected or actual text transform produced zero candidates"
        return to_outcome(False, expected_candidate, actual_candidate, "diff")

    def _is_use_screen(self, test_case: TestCase):
        if self.require_screen == 'never':
            return False
        if self.require_screen == 'always':
            return True
        # 'auto'
        return test_case.input_file is not None


    def run_test_case(self, test_case: TestCase) -> TestCaseOutcome:
        thread_id = threading.current_thread().ident
        use_screen = self._is_use_screen(test_case)
        input_file = test_case.input_file
        _log.debug("[%x] use_screen=%s for require_screen=%s and input=%s (test case %x)", thread_id, use_screen, self.require_screen, None if input_file is None else os.path.basename(input_file), hash(test_case))
        expected_file = test_case.expected_file
        expected_text = read_file_text(expected_file)

        def make_outcome(passed: bool, expected_text_: str, actual_text: Optional[str], message: str) -> TestCaseOutcome:
            return TestCaseOutcome(passed, self.executable, test_case, expected_text_, actual_text, message)

        def check(actual_text: str) -> TestCaseOutcome:
            return self._check(expected_text, actual_text, make_outcome)

        if input_file is None:
            input_lines = []
        else:
            input_lines = read_file_lines(input_file)
        with tempfile.TemporaryDirectory() as tempdir:
            procdef = ProcessDefinition(self.executable, test_case.args, tempdir, test_case.env_dict())
            if use_screen:
                screener = ScreenRunnable(procdef)
                with screener.start():
                    self._pause(self.throttle.pause_duration * 2)
                    _log.debug("[%x] feeding lines to %s from %s", thread_id, os.path.basename(self.executable),
                               None if input_file is None else os.path.basename(input_file))
                    try:
                        LogWatcher(screener.logfile).await_output(self.throttle.await)
                        for i, line in enumerate(input_lines):
                            self._pause()
                            proc = screener.stuff(line, self.stuff_config, i + 1)
                            if proc.returncode != 0:
                                actual_text_ = screener.logfile_text(ignore_failure=True)
                                return make_outcome(False, expected_text, actual_text_, "stuff")
                        if self.stuff_config.eof:
                            screener.stuff_eof()
                        _log.debug("[%x] waiting %s seconds for process to terminate", thread_id, self.throttle.processing_timeout)
                        screener.await_proc(self.throttle.processing_timeout)
                    finally:
                        if not screener.quit():
                            if not screener.finished():
                                screener.kill()
                output = screener.logfile_text(ignore_failure=False)
                if screener.completed_proc is not None and screener.completed_proc.returncode != 0:
                    return make_outcome(False, expected_text, output, f"screen -D -m {self.executable} exit code {screener.completed_proc.returncode}")
            else:
                # if we don't need to send/capture input, then we can just execute
                cmd = [self.executable] + list(test_case.args)
                completed_proc = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, cwd=tempdir, env=test_case.env_dict())
                output = completed_proc.stdout.decode('utf8')
                # TODO log stderr
                if not test_case.check_exit_code(completed_proc.returncode):
                    return make_outcome(False, expected_text, output, f"unexpected exit code {completed_proc.returncode}")
        return check(output)


class TestCaseRunnerFactory(object):

    def __init__(self, throttle: Throttle, stuff_config: StuffConfig, require_screen: str = 'auto'):
        self.stuff_config = stuff_config
        self.throttle = throttle
        self.require_screen = require_screen

    def create(self, executable: str):
        return TestCaseRunner(executable, self.throttle, self.stuff_config, self.require_screen)


class ConcurrencyManager(object):
    
    def __init__(self, runner: TestCaseRunner, concurrency_level: int):
        self.concurrer = threading.Semaphore(concurrency_level)
        self.runner = runner
        self.outcomes_lock = threading.Lock()

    def _run_test_case(self, test_case: TestCase) -> TestCaseOutcome:
        return self.runner.run_test_case(test_case)

    def perform(self, test_case: TestCase, outcomes: Dict[TestCase, TestCaseOutcome], q_name:str=None, i:int=0):
        """Runs a test case and puts the outcome in the given dictionary.

        The q_name and i parameters are only used for log messages."""
        if test_case.input_file is None:
            input_name = None
        else:
            input_name = os.path.basename(test_case.input_file)
        try:
            self.concurrer.acquire()
            try:
                outcome = self._run_test_case(test_case)
                if outcome.passed:
                    _log.debug("%s: case %s (%s) passed", q_name, i + 1, input_name)
                else:
                    _log.info("%s: case %s (%s) failed: %s", q_name, i + 1, input_name, outcome.message)
            finally:
                self.concurrer.release()
        except Exception as e:
            _log.warning("%s: case %s (%s) unhandled exception: %s %s", q_name, i + 1, input_name, type(e).__name__, e)
            exc_info = sys.exc_info()
            info = traceback.format_exception(*exc_info)
            _log.debug("%s: case %s (%s) traceback:\n%s", q_name, i + 1, input_name, "".join(info).strip())
            outcome = TestCaseOutcome(False, '<unknown>', test_case, '', '', f"unhandled: {type(e).__name__} {e}")
        self.outcomes_lock.acquire()
        try:
            outcomes[test_case] = outcome
        finally:
            self.outcomes_lock.release()


def report(outcomes: List[TestCaseOutcome], report_type: str, ofile=sys.stderr):
    for outcome in outcomes:
        q_name = os.path.basename(outcome.executable)
        if outcome.test_case.input_file is None:
            input_name = None
        else:
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


class TestCasesConfig(NamedTuple):

    max_test_cases: int
    filter_pattern: Optional[str]

    def matches(self, test_case: TestCase):
        if self.filter_pattern is None or test_case.input_file is None:
            return True
        filename = os.path.basename(test_case.input_file)
        return fnmatch.fnmatch(filename, self.filter_pattern)


class CppChecker(object):

    def __init__(self, runner_factory: TestCaseRunnerFactory, concurrency_level: int):
        self.runner_factory = runner_factory
        self.concurrency_level = concurrency_level

    # noinspection PyMethodMayBeStatic
    def _detect_test_cases(self, q_dir: str) -> List[TestCase]:
        return detect_test_case_files(q_dir)

    # noinspection PyMethodMayBeStatic
    def _resolve_executable(self, q_dir: str) -> str:
        q_name = os.path.basename(q_dir)
        q_executable = os.path.join(q_dir, 'cmake-build', q_name)
        assert os.path.isfile(q_executable), "not found: " + q_executable
        return q_executable

    def check_cpp(self, cpp_file: str, test_cases_cfg: TestCasesConfig) -> Dict[TestCase, TestCaseOutcome]:
        q_dir = os.path.dirname(cpp_file)
        test_case_files = self._detect_test_cases(q_dir)
        outcomes = {}
        if not test_case_files:
            return outcomes
        q_name = os.path.basename(q_dir)
        _log.info("%s: detected %s test cases", q_name, len(test_case_files))
        q_executable = self._resolve_executable(q_dir)
        runner = self.runner_factory.create(q_executable)
        threads: List[threading.Thread] = []
        concurrency_mgr = ConcurrencyManager(runner, self.concurrency_level)
        for i, test_case in enumerate(test_case_files):
            if test_cases_cfg.max_test_cases is not None and i >= test_cases_cfg.max_test_cases:
                _log.debug("breaking early due to test case limit")
                break
            if not test_cases_cfg.matches(test_case):
                _log.debug("skipping; filter %s rejected test case %s", test_cases_cfg, test_case)
                continue
            t = threading.Thread(target=lambda: concurrency_mgr.perform(test_case, outcomes, q_name, i))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        if not threads:
            _log.warning("all test cases were skipped")
        assert len(threads) == len(outcomes), "not all threads returned an outcome: {} threads but {} outcomes".format(len(threads), len(outcomes))
        return outcomes


def review_outcomes(outcomes: Dict[TestCase, TestCaseOutcome], report_type, q_name=None):
    failures = [outcome for outcome in outcomes.values() if not outcome.passed]
    if failures:
        _log.info("%s: %s failures among %s test cases", q_name, len(failures), len(outcomes))
    else:
        if len(outcomes) > 0:
            _log.info("%s: all %s tests pass", q_name, len(outcomes))
        else:
            _log.warning("zero test cases executed for %s", q_name)
    report(failures, report_type)
    return len(failures)


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
                if f == 'main.cpp':
                    if os.path.exists(os.path.join(root, '.nocheck')):
                        _log.info("skipping %s because of .nocheck file", os.path.basename(root))
                    else:
                        main_cpps.append(os.path.join(root, f))
    if not main_cpps:
        _log.error("no main.cpp files found")
        return 1
    num_threads = args.threads or multiprocessing.cpu_count()
    total_failures = 0
    await_config = PollConfig.from_args_await(args)
    throttle = Throttle(args.pause, await_config, _DEFAULT_PROCESSING_TIMEOUT_SECONDS)
    stuff_config = StuffConfig.from_args(args)
    test_cases_config = TestCasesConfig(args.max_cases, args.filter)
    runner_factory = TestCaseRunnerFactory(throttle, stuff_config, args.require_screen)
    for i, cpp_file in enumerate(sorted(main_cpps)):
        if args.test_cases != 'existing':
            defs_file = os.path.join(os.path.dirname(cpp_file), 'test-cases.json')
            if not os.path.isfile(defs_file):
                if args.test_cases == 'require':
                    raise FileNotFoundError(defs_file)
            else:
                testcases.produce_from_defs(defs_file, onerror='raise')
        cpp_checker = CppChecker(runner_factory, num_threads)
        outcomes = cpp_checker.check_cpp(cpp_file, test_cases_config)
        q_name = os.path.basename(os.path.dirname(cpp_file))
        per_cpp_failures = review_outcomes(outcomes, report_type=args.report, q_name=q_name)
        total_failures += per_cpp_failures
    return 0 if total_failures == 0 else _ERR_TEST_CASE_FAILURES


def main():
    parser = ArgumentParser()
    parser.add_argument("subdirs", nargs='*', help="subdirectories containing executables to test; if none specified, run all")
    hwsuite.add_logging_options(parser)
    parser.add_argument("-p", "--pause", type=float, metavar="DURATION", help="pause duration (seconds)", default=_DEFAULT_PAUSE_DURATION_SECONDS)
    parser.add_argument("-m", "--max-cases", type=int, default=None, metavar="N", help="run at most N test cases per cpp")
    parser.add_argument("-j", "-t", "--threads", type=int, metavar="N", help="concurrency level for test cases; default is cpu count")
    parser.add_argument("--log-input", help="log feeding of input lines at DEBUG level")
    parser.add_argument("--filter", metavar="PATTERN", help="match test case input filenames against PATTERN")
    parser.add_argument("--report", metavar="ACTION", choices=_REPORT_CHOICES, default='diff', help=f"what to print on test case failure; one of {_REPORT_CHOICES}; default is 'diff'")
    parser.add_argument("--stuff", metavar="MODE", choices=_STUFF_MODES, default='auto', help="how to interpret input lines sent to process via `screen -X stuff`: 'auto' or 'strict'")
    parser.add_argument("--test-cases", metavar="MODE", choices=_TEST_CASES_CHOICES, help=f"test case generation mode; choices are {_TEST_CASES_CHOICES}; default 'auto' means attempt to re-generate")
    parser.add_argument("--project-dir", metavar="DIR", help="project directory (if not current directory)")
    parser.add_argument("--await", type=float, metavar="INTERVAL", help="poll with specified interval for text on process output stream before sending input")
    parser.add_argument("--require-screen", choices=('auto', 'always', 'never'), default='auto', help="how to decide whether to use `screen` to run executable; default is 'auto', which means only when input is to be sent to process")
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    try:
        return _main(args)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
