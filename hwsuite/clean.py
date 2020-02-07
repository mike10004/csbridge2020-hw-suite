#!/usr/bin/env python3

from argparse import ArgumentParser
import os
import os.path
import sys
import fnmatch
import logging
import shutil
import hwsuite


_log = logging.getLogger(__name__)


def clean(proj_root, cmake_dir_pattern='cmake-build*', stage_dir_basename='stage'):
    for root, dirs, files in os.walk(proj_root):
        for direc in dirs:
            if fnmatch.fnmatch(direc, cmake_dir_pattern):
                direc_path = os.path.join(root, direc)
                _log.debug("deleting directory %s", direc_path)
                shutil.rmtree(direc_path)
    stage_dir = os.path.join(proj_root, stage_dir_basename)
    if os.path.isdir(stage_dir):
        _log.debug("deleting %s", stage_dir)
        shutil.rmtree(stage_dir)


def main():
    parser = ArgumentParser()
    parser.add_argument("project_root", nargs='?')
    args = parser.parse_args()
    proj_root = args.project_root or hwsuite.find_proj_root()
    clean(proj_root)
    return 0
