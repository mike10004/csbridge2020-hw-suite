#!/usr/bin/env python3

"""
    question.py generates a new question subdirectory
"""
import argparse
import json
import re
import shutil
import logging
import os.path
import sys
from argparse import ArgumentParser
from typing import Iterable, Optional

import hwsuite


_log = logging.getLogger(__name__)
_DEFAULT_MODE = 'safe'
_QUESTIONMD_TEMPLATE = """\
# Question {n}

Write a program...
"""

_CMAKELISTSTXT_TEMPLATE = """
cmake_minimum_required(VERSION 3.7)
project({q_name})

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_FLAGS "${{CMAKE_CXX_FLAGS}} -pedantic -Werror")

add_executable({q_name} main.cpp)
"""

_MAINCPP_TEMPLATE = """\
// {author}
// {project_name} question {n}

#include <iostream>

using namespace std;

int main() {{
    cout << "{q_name} executed" << endl;
    return 0;
}}
"""

_CAT_CMAKELISTS = 'cmakelists'
_CAT_QUESTIONMD = 'question'
_CAT_MAIN = 'main'
_CAT_TESTCASES = 'testcases'

_FILE_CATEGORIES = {_CAT_CMAKELISTS, _CAT_QUESTIONMD, _CAT_MAIN, _CAT_TESTCASES}


def _write_text(text: str, output_file: str):
    with open(output_file, 'w') as ofile:
        ofile.write(text)


class Questioner(object):

    def __init__(self, proj_dir: str, includes: Iterable[str]=tuple(), excludes: Iterable[str]=tuple()):
        self.proj_dir = proj_dir
        self.includes = frozenset(includes)
        self.excludes = frozenset(excludes)

    def detect_next_qname(self) -> str:
        child_dirs = []
        for root, dirs, _ in os.walk(self.proj_dir):
            for d in dirs:
                child_dirs.append(os.path.join(root, d))
            break
        q_names = list(filter(lambda d_: re.match(r'^q\d+$', d_), map(os.path.basename, child_dirs)))
        q_numerals = []
        for q_name in q_names:
            try:
                q_numerals.append(int(q_name[1:]))
            except ValueError as e:
                _log.debug("failed to parse numeral from q_dir %s due to %s", q_name, e)
        _log.debug("existing q names: %s; numerals = %s", q_names, q_numerals)
        if not q_numerals:
            return 'q1'
        return "q{}".format(max(q_numerals) + 1)


    def _render(self, template: str, q_name: str, output_file: str, cfg=None):
        cfg = cfg if cfg is not None else hwsuite.get_config(self.proj_dir)
        question_model = cfg.get('question_model', {})
        model = {
            'q_name': q_name,
            'n': q_name[1:],
            'author': '<author>',
            'project_name': 'hw'
        }
        model.update(question_model)
        _write_text(template.format(**model), output_file)

    def _is_populable(self, category: str):
        if self.includes:
            return category in self.includes
        return category not in self.excludes

    def populate(self, q_dir):
        q_name = os.path.basename(q_dir)
        if self._is_populable(_CAT_CMAKELISTS):
            self._render(_CMAKELISTSTXT_TEMPLATE, q_name, os.path.join(q_dir, 'CMakeLists.txt'))
        if self._is_populable(_CAT_QUESTIONMD):
            self._render(_QUESTIONMD_TEMPLATE, q_name, os.path.join(q_dir, 'question.md'))
        if self._is_populable(_CAT_MAIN):
            self._render(_MAINCPP_TEMPLATE, q_name, os.path.join(q_dir, 'main.cpp'))
        test_cases = {
            "input": "{nombre}\n",
            "input_file": "input-template.txt",
            "expected": "Enter your name: {nombre}\nhello, {nombre}\n",
            "expected_file": "expected-template.txt",
            "param_names": ["nombre"],
            "test_cases": [
                ["jane"],
                ["julia"],
                ["jennifer"],
            ]
        }
        if self._is_populable(_CAT_TESTCASES):
            _write_text(json.dumps(test_cases, indent=2), os.path.join(q_dir, 'test-cases.json'))
        _log.debug("populated directory %s", q_dir)

    def config_root_proj(self, q_name):
        root_cmakelists_file = os.path.join(self.proj_dir, 'CMakeLists.txt')
        with open(root_cmakelists_file, 'a') as ofile:
            print(f"add_subdirectory(\"${{PROJECT_SOURCE_DIR}}/{q_name}\" \"${{PROJECT_SOURCE_DIR}}/{q_name}/cmake-build\")", file=ofile)
        _log.debug("appended subdirectory line to %s", root_cmakelists_file)


def _parse_cludes(listing: Optional[str]) -> Iterable[str]:
    if listing is None:
        return frozenset()
    return frozenset([item.strip() for item in listing.split(",")])


def _main_raw(proj_dir=None, q_name=None, mode=_DEFAULT_MODE, includes: Optional[str]=None, excludes: Optional[str]=None) -> str:
    """Does the work you want and returns the path of the new directory."""
    proj_dir = os.path.abspath(proj_dir or hwsuite.find_proj_root())
    questioner = Questioner(proj_dir, includes=_parse_cludes(includes), excludes=_parse_cludes(excludes))
    q_name = q_name if q_name is not None else questioner.detect_next_qname()
    if os.path.isabs(q_name):
        raise ValueError("'name' should be basename or relative path, not an absolute path")
    q_dir = os.path.join(proj_dir, q_name)
    if mode == 'replace' and os.path.exists(q_dir):
        shutil.rmtree(q_dir)
    os.makedirs(q_dir, exist_ok=(mode == 'overwrite'))
    questioner.populate(q_dir)
    questioner.config_root_proj(q_name)
    _log.info("%s created", hwsuite.describe_path(q_dir))
    return q_dir


def _main(args: argparse.Namespace) -> int:
    _main_raw(args.project_dir, args.name, args.mode, args.includes, args.excludes)
    return 0


def main():
    parser = ArgumentParser()
    parser.add_argument("name", nargs='?', help="name of subdirectory, e.g. 'q2'")
    hwsuite.add_logging_options(parser)
    parser.add_argument("--mode", default=_DEFAULT_MODE, choices=('safe', 'overwrite', 'replace'))
    parser.add_argument("--project-dir", metavar="DIR", help="project directory; default is working directory")
    parser.add_argument("--include", metavar="CATEGORY", help=f"comma-separated list of file categories to include; choices are {_FILE_CATEGORIES}")
    parser.add_argument("--exclude", metavar="CATEGORY", help=f"comma-separated list of file categories to exclude; choices are {_FILE_CATEGORIES}")
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    try:
        return _main(args)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
