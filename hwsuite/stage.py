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
from typing import List, Optional, Sequence
import re
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


def _is_cut_any(line) -> bool:
    return re.search(r'//\s*stage:\s*(remove|cut)(\s+.*)?$', line, flags=re.IGNORECASE) is not None


def _is_cut_start(line: str) -> bool:
    return re.search(r'//\s*stage:\s*(remove|cut)\s+start(\s+.*)?$', line, flags=re.IGNORECASE) is not None


def _is_cut_stop(line: str) -> bool:
    return re.search(r'//\s*stage:\s*(remove|cut)\s+stop(\s+.*)?$', line, flags=re.IGNORECASE) is not None


class StageSyntaxException(hwsuite.MessageworthyException):
    pass

class UnstoppedCutException(StageSyntaxException):
    pass


def _is_in_remove_block(all_lines: List[str], line_index: int) -> bool:
    # look backward until you find a cut start or cut stop line; if cut stop, then FALSE; if cut start, then...
    # look foward until you find a cut start or cut stop; if cut stop, then TRUE, if cut start or never found, then ERROR
    if _is_cut_any(all_lines[line_index]):
        return True
    after_cut_start = False
    for i in reversed(range(0, line_index)):
        line = all_lines[i]
        if _is_cut_stop(line):
            return False
        if _is_cut_start(line):
            after_cut_start = True
            break
    if after_cut_start:
        for i in range(line_index + 1, len(all_lines)):
            line = all_lines[i]
            if _is_cut_stop(line):
                return True
        raise UnstoppedCutException("`cut stop` never found")
    return False


def _transfer_lines(src_lines: List[str]) -> List[str]:
    good_lines = []
    for idx, line in enumerate(src_lines):
        if not _is_cut_any(line) and not _is_in_remove_block(src_lines, idx):
            good_lines.append(line)
    return good_lines


def _transfer(src_file, dst_file) -> str:
    """Copy src_file to dst_file, removing lines marked for removal, and return the text written."""
    with open(src_file, 'r') as ifile:
        src_lines = [line for line in ifile]
    good_lines = _transfer_lines(src_lines)
    with open(dst_file, 'w') as ofile:
        for line in good_lines:
            ofile.write(line)
    return ''.join(good_lines)


class Stager(object):

    def __init__(self, proj_root: str, cfg: dict):
        self.proj_root = proj_root
        self.cfg = cfg
        self.default_stage_dir_basename = 'stage'
        self.no_clean = False

    def persist_config(self):
        hwsuite.store_config(self.cfg, proj_root=self.proj_root)

    @staticmethod
    def create(proj_root: str) -> 'Stager':
        proj_root = os.path.abspath(proj_root)
        cfg = hwsuite.get_config(proj_root=proj_root)
        return Stager(proj_root, cfg)

    def detect_subdirs(self) -> List[str]:
        subdirs = []
        for root, dirs, files in os.walk(self.proj_root):
            for direc in dirs:
                if fnmatch.fnmatch(direc, 'q*'):
                    subdirs.append(os.path.join(root, direc))
            break  # only examine direct descendents
        return subdirs

    # noinspection PyMethodMayBeStatic
    def find_cpp_files(self, subdirs: List[str]):
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
        return cpp_files_for_staging

    # noinspection PyMethodMayBeStatic
    def map_to_destination(self, cpp_files_for_staging: Sequence[str], stage_dir: str, prefix: str):
        dest_mapping = {}
        for cpp_file in cpp_files_for_staging:
            dest_pathname = os.path.join(stage_dir, prefix + os.path.basename(os.path.dirname(cpp_file)) + '.cpp')
            if dest_pathname in dest_mapping.values():
                _log.warning("name conflict: multiple sources map to %s", dest_pathname)
                return 0
            dest_mapping[cpp_file] = dest_pathname
        return dest_mapping

    def stage(self, prefix: Optional[str]=None, stage_dir: Optional[str]=None, subdirs: Optional[List[str]]=None) -> int:
        """Stages files and returns number of files staged."""
        if prefix is not None and not prefix.strip():
            raise ValueError("prefix must contain non-whitespace")
        if prefix is None:
            prefix = self.cfg.get('stage_prefix', None)
            # TODO detect prefix from git user.email and root CMakeLists.txt project name
            if prefix is None:
                raise PrefixNotDefinedException("prefix must be specified if 'stage_prefix' is not defined in .hwconfig.json")
        else:
            self.cfg['stage_prefix'] = prefix
            self.persist_config()
        if not subdirs:
            subdirs = self.detect_subdirs()
        cpp_files_for_staging = self.find_cpp_files(subdirs)
        if not cpp_files_for_staging:
            _log.warning("zero .cpp files found to stage")
            return 0
        stage_dir = os.path.abspath(stage_dir or os.path.join(self.proj_root, self.default_stage_dir_basename))
        if not self.no_clean and os.path.isdir(stage_dir):
            clean(stage_dir)
        dest_mapping = self.map_to_destination(cpp_files_for_staging, stage_dir, prefix)
        for src_file, dst_file in dest_mapping.items():
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            try:
                _transfer(src_file, dst_file)
            except UnstoppedCutException:
                raise UnstoppedCutException(f"unstopped cut in {src_file}")
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
        stager = Stager.create(proj_root)
        num_staged = stager.stage(args.prefix, args.stage_dir)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
    if num_staged == 0:
        # warning message already printed by logger
        return 1
    return 0
