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
import hwsuite


_log = logging.getLogger(__name__)

_QUESTIONMD_TEMPLATE = """\
# Question {n}

Write a program...
"""

_CMAKELISTSTXT_TEMPLATE = """
cmake_minimum_required(VERSION 3.7)
project({q_name})

set(CMAKE_CXX_STANDARD 14)

add_executable({q_name} main.cpp)
"""

_MAINCPP_TEMPLATE = """\
// {author}
// Question {n}

#include <iostream>

using namespace std;

int main() {{
    cout << "{q_name} executed" << endl;
    return 0;
}}
"""


def _write_text(text: str, output_file: str):
    with open(output_file, 'w') as ofile:
        ofile.write(text)


class Questioner(object):

    def __init__(self, proj_dir: str):
        self.proj_dir = proj_dir

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
        cfg = cfg or hwsuite.get_config(proj_root=self.proj_dir)
        question_model = cfg.get('question_model', {})
        model = {
            'q_name': q_name,
            'n': q_name[1:],
            'author': '<author>',
        }
        model.update(question_model)
        _write_text(template.format(**model), output_file)


    def populate(self, q_dir):
        q_name = os.path.basename(q_dir)
        self._render(_CMAKELISTSTXT_TEMPLATE, q_name, os.path.join(q_dir, 'CMakeLists.txt'))
        self._render(_QUESTIONMD_TEMPLATE, q_name, os.path.join(q_dir, 'question.md'))
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
        _write_text(json.dumps(test_cases, indent=2), os.path.join(q_dir, 'test-cases.json'))
        _log.debug("populated directory %s", q_dir)


    def config_root_proj(self, q_name):
        root_cmakelists_file = os.path.join(self.proj_dir, 'CMakeLists.txt')
        with open(root_cmakelists_file, 'a') as ofile:
            print(f"add_subdirectory(\"${{PROJECT_SOURCE_DIR}}/{q_name}\" \"${{PROJECT_SOURCE_DIR}}/{q_name}/cmake-build\")", file=ofile)
        _log.debug("appended subdirectory line to %s", root_cmakelists_file)


def _main(args: argparse.Namespace) -> int:
    proj_dir = os.path.abspath(args.project_dir or hwsuite.find_proj_root())
    questioner = Questioner(proj_dir)
    q_name = args.name if args.name is not None else questioner.detect_next_qname()
    if os.path.isabs(q_name):
        raise ValueError("'name' should be basename or relative path, not an absolute path")
    q_dir = os.path.join(proj_dir, q_name)
    if args.mode == 'replace' and os.path.exists(q_dir):
        shutil.rmtree(q_dir)
    os.makedirs(q_dir, exist_ok=(args.mode == 'overwrite'))
    questioner.populate(q_dir)
    questioner.config_root_proj(q_name)
    return 0

def main():
    parser = ArgumentParser()
    parser.add_argument("name", nargs='?', help="name of subdirectory, e.g. 'q2'")
    hwsuite.add_logging_options(parser)
    parser.add_argument("--mode", default='safe', choices=('safe', 'overwrite', 'replace'))
    parser.add_argument("--project-dir", metavar="DIR", help="project directory; default is working directory")
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    try:
        return _main(args)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
