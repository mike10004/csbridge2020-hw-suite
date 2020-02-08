#!/usr/bin/env python3

import os
import argparse
import sys

import hwsuite
import logging


_log = logging.getLogger(__name__)

_ROOT_CMAKELISTS_TXT_TEMPLATE = """\
cmake_minimum_required(VERSION 3.7)
project({project_name})
"""

_GITIGNORE_TEXT = """\
cmake-build*/
/stage/
__pycache__/
test-cases/
*.pyc
"""


class AlreadyInitializedException(hwsuite.MessageworthyException):
    pass


def init_file(pathname: str, safety_mode: str, contents: str, write_mode='w'):
    if os.path.exists(pathname):
        _log.debug("already exists: %s (mode=%s)", pathname, safety_mode)
        if safety_mode == 'abort':
            raise AlreadyInitializedException(f"already exists: {pathname}")
        if safety_mode == 'ignore':
            return
    with open(pathname, write_mode) as ofile:
        ofile.write(contents)


def do_init(proj_dir, project_name, safety_mode, cfg_filename=hwsuite.CFG_FILENAME) -> int:
    os.makedirs(proj_dir, exist_ok=True)
    cfg_pathname = os.path.join(proj_dir, cfg_filename)
    init_file(cfg_pathname, safety_mode, '')
    cmakelists_pathname = os.path.join(proj_dir, 'CMakeLists.txt')
    cmakelists_text = _ROOT_CMAKELISTS_TXT_TEMPLATE.format(project_name=project_name)
    init_file(cmakelists_pathname, safety_mode, cmakelists_text)
    gitignore_pathname = os.path.join(proj_dir, '.gitignore')
    init_file(gitignore_pathname, safety_mode, _GITIGNORE_TEXT, write_mode='a')
    _log.info("%s initialized", hwsuite.describe_path(proj_dir))
    return 0


def main():
    parser = argparse.ArgumentParser()
    hwsuite.add_logging_options(parser)
    parser.add_argument("project_dir", nargs='?', help="directory to initialize (if not $PWD)")
    parser.add_argument("--safety", metavar='MODE', choices=('ignore', 'cautious', 'overwrite'), default='ignore',
                        help="what to do if project files already exist; one of 'ignore', 'abort', or 'overwrite'")
    parser.add_argument("--name", default='hw', help="set CMake project name")
    args = parser.parse_args()
    try:
        hwsuite.configure_logging(args)
        proj_dir = args.project_dir or os.getcwd()
        return do_init(proj_dir, args.name, args.safety)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
