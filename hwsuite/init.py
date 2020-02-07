#!/usr/bin/env python3

import os
import argparse
from pathlib import Path

import hwsuite

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


class AlreadyInitializedException(Exception):
    pass


def touch(pathname):
    Path(pathname).touch()


def do_init(proj_dir, project_name, unsafe=False, cfg_filename=hwsuite.CFG_FILENAME) -> int:
    cfg_pathname = os.path.join(proj_dir, cfg_filename)
    if not unsafe and os.path.exists(cfg_pathname):
        raise AlreadyInitializedException(f"already exists: {cfg_pathname}")
    os.makedirs(proj_dir, exist_ok=True)
    touch(cfg_pathname)
    cmakelists_pathname = os.path.join(proj_dir, 'CMakeLists.txt')
    if not unsafe and os.path.exists(cmakelists_pathname):
        raise AlreadyInitializedException(f"already exists: {cmakelists_pathname}")
    cmakelists_text = _ROOT_CMAKELISTS_TXT_TEMPLATE.format(project_name=project_name)
    with open(cmakelists_pathname, 'w') as ofile:
        ofile.write(cmakelists_text)
    with open(os.path.join(proj_dir, '.gitignore'), 'a') as ofile:
        print(_GITIGNORE_TEXT, file=ofile)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", nargs='*', help="directory to initialize (if not $PWD)")
    parser.add_argument("--unsafe", action="store_true")
    parser.add_argument("--name", default='hw', help="set CMake project name")
    args = parser.parse_args()
    proj_dir = args.project_dir or os.getcwd()
    return do_init(proj_dir, args.name, unsafe=args.unsafe)
