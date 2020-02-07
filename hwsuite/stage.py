#!/usr/bin/env python3

import argparse
import glob
from argparse import ArgumentParser
import os
import os.path
import sys
import fnmatch
import logging
import shutil
from typing import List

import hwsuite


_log = logging.getLogger(__name__)


class PrefixNotDefinedException(hwsuite.MessageworthyException):
    pass


def clean(stage_dir: str):
    _log.debug("cleaning contents of %s", stage_dir)
    ndirs, nfiles = 0, 0
    for root, dirs, files in os.walk(stage_dir):
        for dir_basename in dirs:
            dir_pathname = os.path.join(root, dir_basename)
            shutil.rmtree(dir_pathname)
            ndirs += 1
        for filename in files:
            pathname = os.path.join(root, filename)
            os.remove(pathname)
            nfiles += 1
        break  # first pass deletes everything
    if ndirs > 0 or nfiles > 0:
        _log.info("%s directories and %s files deleted", ndirs, nfiles)


def stage(proj_root: str, prefix: str=None, stage_dir: str=None, subdirs: List[str]=None, cfg: dict=None, default_stage_dir_basename='stage', no_clean=False) -> int:
    """Stages files and returns number of files staged."""
    proj_root = os.path.abspath(proj_root)
    if prefix is None:
        cfg = cfg or hwsuite.get_config(proj_root=proj_root)
        prefix = cfg.get('stage_prefix', None)
        # TODO detect prefix from git user.email and root CMakeLists.txt project name
        if prefix is None:
            raise PrefixNotDefinedException("prefix must be specified if 'stage_prefix' is not defined in .hwconfig.json")
    if not subdirs:
        if subdirs is None:
            subdirs = []
        for root, dirs, files in os.walk(proj_root):
            for direc in dirs:
                if fnmatch.fnmatch(direc, 'q*'):
                    subdirs.append(os.path.join(root, direc))
            break  # only examine direct descendents
    _log.debug("drawing cpp files from %s", subdirs)
    cpp_files_for_staging = []
    for subdir in subdirs:
        if os.path.exists(os.path.join(subdir, '.nostage')):
            _log.debug("skipping %s because .nostage was found", subdir)
            continue
        main_cpp = os.path.join(subdir, 'main.cpp')
        if not os.path.exists(main_cpp):
            cpp_files = glob.glob(os.path.join(subdir, '*.cpp'))
            _log.debug("%d .cpp files found in %s", len(cpp_files), subdir)
            if not cpp_files:
                continue
            if len(cpp_files) > 1:
                _log.warning("skipping %s because multiple cpp files found", subdir)
                continue
            main_cpp = cpp_files[0]
        cpp_files_for_staging.append(main_cpp)
    if not cpp_files_for_staging:
        _log.warning("zero .cpp files found to stage")
        return 0
    stage_dir = os.path.abspath(stage_dir or os.path.join(proj_root, default_stage_dir_basename))
    if not no_clean and os.path.isdir(stage_dir):
        clean(stage_dir)
    dest_mapping = {}
    for cpp_file in cpp_files_for_staging:
        dest_pathname = os.path.join(stage_dir, prefix + os.path.basename(os.path.dirname(cpp_file)) + '.cpp')
        if dest_pathname in dest_mapping.values():
            _log.warning("name conflict: multiple sources map to %s", dest_pathname)
            return 0
        dest_mapping[cpp_file] = dest_pathname
    for src_file, dst_file in dest_mapping.items():
        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
        shutil.copy(src_file, dst_file)
        _log.debug("copied %s -> %s", src_file, dst_file)
    return len(dest_mapping)


def main():
    parser = ArgumentParser()
    parser.add_argument("prefix", nargs='?', help="prefix (if not stored in .hwconfig.json)")
    parser.add_argument("--project-root", metavar="DIR")
    parser.add_argument("--stage-dir", metavar="DIR", help="destination directory")
    args = parser.parse_args()
    try:
        proj_root = os.path.abspath(args.project_root or hwsuite.find_proj_root())
        num_staged = stage(proj_root, args.prefix, args.stage_dir)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
    if num_staged == 0:
        # warning message already printed by logger
        return 1
    return 0
