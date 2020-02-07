#!/usr/bin/env python3

"""
    check.py builds the executables and then runs the test cases.
    
    Your system must have `screen` installed.
"""

import difflib
import fnmatch
import sys
import logging
import threading
import uuid
import tempfile
import os.path
import subprocess
import time
import make_test_cases
from subprocess import PIPE, DEVNULL
from argparse import ArgumentParser
from typing import List, Tuple, Optional, NamedTuple


_log = logging.getLogger(__name__)
_DEFAULT_PAUSE_DURATION_SECONDS = 0.5


class CommandException(Exception):
    pass


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


def _cmd(cmd_list, err_msg="Command Line Error", allow_nonzero_exit=False) -> str:
    proc = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if allow_nonzero_exit or proc.returncode != 0:
        raise CommandException("exit code {}; {}\n{}".format(proc.returncode, err_msg, proc.stderr.decode('utf8')))
    return proc.stdout.decode('utf8')


def detect_test_case_files(q_dir: str) -> List[Tuple[Optional[str], str]]:
    test_cases = []
    for root, dirs, files in os.walk(q_dir):
        for f in files:
            if f.startswith('input'):
                input_file = os.path.join(root, f)
                expected_file = os.path.join(root, "expected-output" + f[5:])
                test_cases.append((input_file, expected_file))
    if not test_cases:
        expected_file = os.path.join(q_dir, 'expected-output.txt')
        if os.path.isfile(expected_file):
            return [(None, expected_file)]
        return []
    return sorted(test_cases)


class TestCaseOutcome(NamedTuple):

    passed: bool
    executable: str
    input_file: Optional[str]
    expected_text: str
    actual_text: str
    message: str


class TestCaseRunner(object):

    def __init__(self, executable, pause_duration=_DEFAULT_PAUSE_DURATION_SECONDS, log_input=False, stuff_mode='auto'):
        self.executable = executable
        self.pause_duration = pause_duration
        self.log_input = log_input
        self.stuff_mode = stuff_mode

    def _pause(self, duration=None):
        time.sleep(self.pause_duration if duration is None else duration)

    def _prepare_stuff(self, line):
        if self.stuff_mode == 'auto' and line[-1] != "\n":
            line += "\n"
        return line

    def run_test_case(self, input_file: Optional[str], expected_file: str):
        tid = threading.current_thread().ident
        expected_text = read_file_text(expected_file)

        def outcome(passed: bool, actual_text: Optional[str], message: str):
            return TestCaseOutcome(passed, self.executable, input_file, expected_text, actual_text, message)

        def check(actual_text: str):
            if actual_text != expected_text:
                return outcome(False, actual_text, "diff")
            return outcome(True, actual_text, "ok")

        if input_file is None:
            output = _cmd([self.executable])
            return check(output)
        
        input_lines = read_file_lines(input_file)
        case_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tempdir:
            exitcode = subprocess.call(['screen', '-L', '-S', case_id, '-d', '-m', self.executable], cwd=tempdir)
            if exitcode != 0:
                return outcome(False, None, f"screen start failure {exitcode}")
            _log.debug("[%s] screen session %s started for %s; feeding lines from %s", tid, case_id, os.path.basename(self.executable), os.path.basename(input_file))
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
                        return outcome(False, read_file_text(screenlog, True), msg)
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
    
    def __init__(self, runner, concurrency_level: int, q_name, outcomes):
        self.concurrer = threading.Semaphore(concurrency_level)
        self.runner = runner
        self.q_name = q_name
        self.outcomes = outcomes
        self.outcomes_lock = threading.Lock()

    def perform(self, test_case, i):
        input_file, expected_file = test_case
        self.concurrer.acquire()
        try:
            outcome = self.runner.run_test_case(input_file, expected_file)
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
        input_name = os.path.basename(outcome.input_file)
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


def main():
    parser = ArgumentParser()
    parser.add_argument("subdirs", nargs='*', help="subdirectories containing executables to test; if none specified, run all")
    parser.add_argument("-l", "--log-level", metavar="LEVEL", choices=('DEBUG', 'INFO', 'WARNING', 'ERROR'), default='INFO', help="set log level")
    parser.add_argument("-p", "--pause", type=float, metavar="DURATION", help="pause duration (seconds)", default=_DEFAULT_PAUSE_DURATION_SECONDS)
    parser.add_argument("-m", "--max-cases", type=int, default=None, metavar="N", help="run at most N test cases per cpp")
    parser.add_argument("-j", "-t", "--threads", type=int, default=4, metavar="N", help="concurrency level for test cases")
    parser.add_argument("--log-input", help="log feeding of input lines at DEBUG level")
    parser.add_argument("--filter", metavar="PATTERN", help="match test case input filenames against PATTERN")
    parser.add_argument("--report", metavar="ACTION", choices=('diff', 'full', 'repr', 'none'), default='diff', help="what to print on test case failure")
    parser.add_argument("--stuff", metavar="MODE", choices=('auto', 'strict'), default='auto', help="how to interpret input lines sent to process via `screen -X stuff`: 'auto' or 'strict'")
    parser.add_argument("--test-cases", metavar="MODE", choices=('auto', 'require', 'existing'), help="test case generation mode; 'auto' means attempt to re-generate")
    args = parser.parse_args()
    logging.basicConfig(level=logging.__dict__[args.log_level])
    this_file = os.path.abspath(__file__)
    proj_dir = os.path.dirname(this_file)  # also might want to handle the case where script piped in on stdin
    _log.debug("this project dir is %s, derived from %s", proj_dir, os.path.basename(this_file))
    assert proj_dir and os.path.isdir(proj_dir), "failed to detect project directory"
    build_script = os.path.join(proj_dir, 'build.sh')
    _log.debug("building executables by running %s", build_script)
    _cmd(['bash', build_script], err_msg="build error")
    _log.debug("done building executables")
    main_cpps = []
    if args.subdirs:
        _log.debug("limiting tests to subdirectories: %s", args.subdirs)
        main_cpps += [os.path.join(proj_dir, subdir, 'main.cpp') for subdir in args.subdirs]
    else:
        _log.debug("searching %s for main.cpp files", proj_dir)
        for root, dirs, files in os.walk(proj_dir):
            for f in files:
                if f == 'main.cpp':
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
                make_test_cases.produce_from_defs(defs_file)
        check_cpp(cpp_file, args.threads, args.pause, args.max_cases, args.log_input, args.filter, args.report, args.stuff)
    return 0


if __name__ == '__main__':
    exit(main())
