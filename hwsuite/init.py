#!/usr/bin/env python3
import json
import os
import argparse
import sys
from typing import Dict, Any

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
_SAFETY_MODES = ('ignore', 'cautious', 'overwrite')
_DEFAULT_SAFETY_MODE = 'ignore'

class AlreadyInitializedException(hwsuite.MessageworthyException):
    pass


def init_file(pathname: str, safety_mode: str, contents: str, write_mode='w'):
    if safety_mode not in _SAFETY_MODES:
        raise ValueError(f"safety_mode must be one of {_SAFETY_MODES}")
    if os.path.exists(pathname):
        _log.debug("already exists: %s (mode=%s)", pathname, safety_mode)
        if safety_mode == 'cautious':
            raise AlreadyInitializedException(f"already exists: {pathname}")
        if safety_mode == 'ignore':
            return
    with open(pathname, write_mode) as ofile:
        ofile.write(contents)


def do_init(proj_dir: str, safety_mode: str, hwconfig: Dict[str, Any], cfg_filename=hwsuite.CFG_FILENAME) -> int:
    os.makedirs(proj_dir, exist_ok=True)
    cfg_pathname = os.path.join(proj_dir, cfg_filename)
    init_file(cfg_pathname, safety_mode, json.dumps(hwconfig, indent=2))
    cmakelists_pathname = os.path.join(proj_dir, 'CMakeLists.txt')
    project_name = hwconfig.get('question_model', {}).get('project_name', 'hw')
    cmakelists_text = _ROOT_CMAKELISTS_TXT_TEMPLATE.format(project_name=project_name)
    init_file(cmakelists_pathname, safety_mode, cmakelists_text)
    gitignore_pathname = os.path.join(proj_dir, '.gitignore')
    # ignore safety mode for gitignore; if you already have it, then you have a git repo where you can undo changes
    init_file(gitignore_pathname, 'overwrite', _GITIGNORE_TEXT, write_mode='a')
    _log.info("%s initialized", hwsuite.describe_path(proj_dir))
    return 0


def _main(proj_root, safety_mode: str=_DEFAULT_SAFETY_MODE, name: str=None, author: str=None):
    q_model = {}
    hwconfig = {
        'question_model': q_model
    }
    if author is not None:
        q_model['author'] = author
    if name is not None:
        q_model['project_name'] = name
    return do_init(proj_root, safety_mode, hwconfig)


def main():
    parser = argparse.ArgumentParser()
    hwsuite.add_logging_options(parser)
    parser.add_argument("proj_root", nargs='?', help="directory to initialize (if not $PWD)")
    parser.add_argument("--safety", metavar='MODE', choices=_SAFETY_MODES, default=_DEFAULT_SAFETY_MODE,
                        help="what to do if project files already exist; one of 'ignore', 'abort', or 'overwrite'")
    parser.add_argument("--name", default='hw', help="set CMake project name")
    parser.add_argument("--author", help="set author (for main.cpp template)")
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    try:
        proj_root = args.proj_root or os.getcwd()
        return _main(proj_root, safety_mode=args.safety, name=args.name, author=args.author)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
