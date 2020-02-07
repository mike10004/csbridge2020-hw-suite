#!/usr/bin/env python3

# make_test_cases.py
import json
import math
import os.path
import sys
import traceback
from argparse import ArgumentParser
from typing import NamedTuple, List, Dict, Any, Optional
import logging


_log = logging.getLogger(__name__)
_DEFAULT_CASE_ID_PRECISION = 2
_DEFAULT_DEFINITIONS_FILENAME = "test-cases.json"
_DEFAULT_TEST_CASES_DIRNAME = "test-cases"


def to_pathname(filename, disable_mkdir=False):
    pathname = os.path.join(os.path.dirname(__file__), 'test-cases', filename)
    if not disable_mkdir:
        os.makedirs(os.path.dirname(pathname), exist_ok=True)
    return pathname


def _read_file_text(pathname) -> str:
    with open(pathname, 'r') as ifile:
        return ifile.read()


class ParameterSource(NamedTuple):
    
    input_text_template: str
    expected_text_template: str
    test_cases: List[Dict[str, Any]]
    case_id_precision: Optional[int]
    
    def __str__(self):
        return f"ParameterSource<num_test_cases={len(self.test_cases)}>"
    
    def precision(self):
        if self.case_id_precision is not None:
            return self.case_id_precision
        return 1 + int(math.log10(len(self.test_cases)))
    
    def render_input_text(self, test_case):
        return self.input_text_template.format(**test_case)
    
    def render_expected_text(self, test_case):
        return self.expected_text_template.format(**test_case)
    
    @staticmethod
    def load(model: Dict, root_dir: str) -> 'ParameterSource':
        test_cases = []
        input_text_template = None
        if 'input' in model:
            input_text_template = model['input']
        elif 'input_file' in model:
            path = model['input_file']
            if not os.path.isabs(path):
                path = os.path.join(root_dir, path)
            input_text_template = _read_file_text(path)
        if input_text_template is None:
            raise ValueError("model must define 'input' or 'input_file'")
        expected_text_template = None
        if 'expected' in model:
            expected_text_template = model['expected']
        elif 'expected_file' in model:
            path = model['expected_file']
            if not os.path.isabs(path):
                path = os.path.join(root_dir, path)
            expected_text_template = _read_file_text(path)
        if expected_text_template is None:
            raise ValueError("model must define 'expected' or 'expected_file'")
        try:
            param_names = None
            for test_case in model['test_cases']:
                if isinstance(test_case, dict):
                    test_cases.append(test_case)
                else:
                    case_dict = {}
                    param_names = param_names or model.get('param_names', None)
                    if param_names is None:
                        raise ValueError("'param_names' must be defined if array test cases are defined")
                    for i in range(len(param_names)):
                        case_dict[param_names[i]] = test_case[i]
                    test_cases.append(case_dict)
        except KeyError:
            _log.warning("test cases not defined")
            pass
        precision = model.get('case_id_precision', None)
        return ParameterSource(input_text_template, expected_text_template, test_cases, precision)


def write_cases(param_source: ParameterSource, dest_dir: str, suffix=".txt"):
    nsuccesses = 0
    for i, test_case in enumerate(param_source.test_cases):
        try:
            rendered_input = param_source.render_input_text(test_case)
            case_id = ("{0:0" + str(param_source.precision()) + "d}").format(i + 1)
            input_filename = f"input{case_id}{suffix}"
            input_pathname = os.path.join(dest_dir, input_filename)
            os.makedirs(os.path.dirname(input_pathname), exist_ok=True)
            with open(input_pathname, 'w') as ofile:
                ofile.write(rendered_input)
            expected_filename = f"expected-output{case_id}{suffix}"
            expected_pathname = os.path.join(dest_dir, expected_filename)
            os.makedirs(os.path.dirname(expected_pathname), exist_ok=True)
            with open(expected_pathname, 'w') as ofile:
                ofile.write(param_source.render_expected_text(test_case))
            nsuccesses += 1
        except Exception:
            exc_info = sys.exc_info()
            info = traceback.format_exception(*exc_info)
            _log.debug("writing cases: exception traceback:\n%s", "".join(info).strip())
            e = exc_info[1]
            _log.warning("failed to write cases to %s: %s, %s", dest_dir, type(e), e)
            continue
    _log.debug("%s of %s test cases generated in %s", nsuccesses, len(param_source.test_cases), dest_dir) 


def is_skel_file(pathname, proj_dir):
    pathname = os.path.normpath(os.path.abspath(pathname))
    skel_dir = os.path.normpath(os.path.join(os.path.abspath(proj_dir), 'skel'))
    return pathname.startswith(skel_dir)


def find_all_definitions_files(top_dir: str, filename: str) -> List[str]:
    defs_files = []
    for root, dirs, files in os.walk(top_dir):
        for f in files:
            if f == filename:
                pathname = os.path.join(root, f)
                if not is_skel_file(pathname, top_dir):
                    defs_files.append(pathname)
    return defs_files


def produce_from_defs(defs_file: str, dest_dirname: str = 'test-cases') -> ParameterSource:
    with open(defs_file, 'r') as ifile:
        model = json.load(ifile)
    param_source = ParameterSource.load(model, os.path.dirname(defs_file))
    dest_dir = os.path.join(os.path.dirname(defs_file), dest_dirname)
    write_cases(param_source, dest_dir)
    return param_source


def produce_files(subdirs: Optional[List[str]], definitions_filename: str, dest_dirname: str):
    proj_dir = os.path.dirname(os.path.abspath(__file__))
    if not subdirs:
        defs_files = find_all_definitions_files(proj_dir, definitions_filename)
    else:
        defs_files = map(lambda d: os.path.join(d, definitions_filename), subdirs)
        defs_files = list(filter(os.path.exists, defs_files))
    nsuccesses = 0
    for defs_file in defs_files:
        try:
            produce_from_defs(defs_file, dest_dirname)
            nsuccesses += 1
        except Exception:
            exc_info = sys.exc_info()
            info = traceback.format_exception(*exc_info)
            _log.debug("exception info:\n%s", "".join(info).strip())
            e = exc_info[1]
            _log.warning("failure to load model and write cases from %s: %s, %s", defs_file, type(e), e)
    _log.debug("test cases generated from %s of %s definitions files", nsuccesses, len(defs_files))
    if nsuccesses == 0:
        _log.error("test case generation did not succeed for any of %s definitions files", len(defs_files))
    return nsuccesses


def main():
    parser = ArgumentParser()
    parser.add_argument("subdirs", nargs='*', metavar="DIR", help="subdirectory containing 'test-cases.json` file")
    parser.add_argument("--definitions-filename", metavar="BASENAME", default=_DEFAULT_DEFINITIONS_FILENAME, help="test cases definitions filename to search for, if not 'test-cases.json'")
    parser.add_argument("--dest-dirname", default="test-cases", metavar="BASENAME", help="destination directory name (relative to definitions file location)")
    parser.add_argument("-l", "--log-level", default="INFO", metavar="LEVEL", choices=('DEBUG', 'WARN', 'ERROR', 'INFO'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.__dict__[args.log_level.upper()])
    nsuccesses = produce_files(args.subdirs, args.definitions_filename, args.dest_dirname)
    return 0 if nsuccesses > 0 else 2
