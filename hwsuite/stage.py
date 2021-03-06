#!/usr/bin/env python3

import glob
from argparse import ArgumentParser
import os
import os.path
import sys
import fnmatch
import logging
import shutil
from typing import List, Optional, Sequence, Dict
import re
import hwsuite
from hwsuite import GitRunner


_log = logging.getLogger(__name__)
_SAFE_FILENAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
ERR_NO_STAGABLES = 2

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


def _has_unsafe_chars(s: str) -> bool:
    for ch in s:
        if ch not in _SAFE_FILENAME_CHARS:
            return True
    return False

class StageNameViolationException(hwsuite.MessageworthyException):
    pass


class Stager(object):

    def __init__(self, proj_root: str):
        self.proj_root = proj_root
        self.default_stage_dir_basename = 'stage'
        self.no_clean = False

    def detect_subdirs(self) -> List[str]:
        subdirs = []
        for root, dirs, files in os.walk(self.proj_root):
            for direc in dirs:
                if fnmatch.fnmatch(direc, 'q*'):
                    subdirs.append(os.path.join(root, direc))
            break  # only examine direct descendents
        return subdirs

    # noinspection PyMethodMayBeStatic
    def find_code_files(self, subdirs: List[str], patterns=('*.h', '*.cpp', '*.cc', '*.hpp')) -> List[str]:
        _log.debug("drawing .h and .cpp files from %s", subdirs)
        code_files = []
        for subdir in subdirs:
            if os.path.exists(os.path.join(subdir, '.nostage')):
                _log.debug("skipping %s because .nostage was found", subdir)
                continue
            for pattern in patterns:
                files = glob.glob(os.path.join(subdir, pattern))
                _log.debug("%d files matching %s found in %s", len(files), pattern, subdir)
                code_files += files
        return code_files

    # noinspection PyMethodMayBeStatic
    def map_to_destination(self, cpp_files_for_staging: Sequence[str], stage_dir: str, prefix: str) -> Dict[str, str]:
        dest_mapping = {}
        for cpp_file in cpp_files_for_staging:
            basename = os.path.basename(cpp_file)
            if basename.lower() == 'main.cpp':
                dest_pathname = os.path.join(stage_dir, prefix + os.path.basename(os.path.dirname(cpp_file)) + '.cpp')
            else:
                dest_pathname = os.path.join(stage_dir, basename)
            dest_mapping[cpp_file] = dest_pathname
        dest_mapping_values = dest_mapping.values()
        if len(set(dest_mapping_values)) != len(dest_mapping_values):
            raise StageNameViolationException("name conflict in mapped destinations: %s", dest_mapping_values)
        return dest_mapping

    def stage(self, prefix: str, stage_dir: Optional[str]=None, subdirs: Optional[List[str]]=None) -> int:
        """Stages files and returns number of files staged."""
        if prefix is not None:
            if not prefix.strip():
                raise ValueError("prefix must contain non-whitespace")
        if not subdirs:
            subdirs = self.detect_subdirs()
        files_for_staging = self.find_code_files(subdirs)
        if not files_for_staging:
            _log.warning("zero .cpp files found to stage")
            return ERR_NO_STAGABLES
        stage_dir = os.path.abspath(stage_dir or os.path.join(self.proj_root, self.default_stage_dir_basename))
        if not self.no_clean and os.path.isdir(stage_dir):
            clean(stage_dir)
        dest_mapping = self.map_to_destination(files_for_staging, stage_dir, prefix)
        for src_file, dst_file in dest_mapping.items():
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            try:
                _transfer(src_file, dst_file)
            except UnstoppedCutException:
                raise UnstoppedCutException(f"unstopped cut in {src_file}")
            _log.debug("copied %s -> %s", src_file, dst_file)
        return len(dest_mapping)


def suggest_prefix(cfg, proj_root, git_runner=None) -> str:
    email = cfg.get('question_model', {}).get('author', None)
    if email is None:
        if not os.path.isdir(os.path.join(proj_root, '.git')):
            raise PrefixNotDefinedException(
                "prefix not defined and this is not a git repo, so username could not be guessed")
        if git_runner is None:
            git_runner = GitRunner()
        email = git_runner.run(['config', 'user.email']).rstrip()
        _log.debug("acquired email address from git config: %s", email)
    else:
        _log.debug("acquired email address from question model: %s", email)
    assert email, "email is malformed (empty?)"
    if '@' in email:
        username = email.split('@', 1)[0]
    else:
        username = email
    project_name = cfg.get('question_model', {}).get('project_name', None)
    if project_name is None:
        raise PrefixNotDefinedException("prefix not defined and project name could not be guessed")
    if username is None:
        raise PrefixNotDefinedException("prefix not defined and username could not be guessed")
    if _has_unsafe_chars(project_name) or _has_unsafe_chars(username):
        raise PrefixNotDefinedException("auto prefix contains unsafe chars")
    return f"{username}_{project_name}_"


def require_prefix(cfg, proj_root) -> str:
    prefix = cfg.get('stage_prefix', None)
    if prefix is None:
        prefix = suggest_prefix(cfg, proj_root)
        cfg['stage_prefix'] = prefix
        hwsuite.store_config(cfg, proj_root=proj_root)
        _log.info("persisted prefix %s to project config", prefix)
    return prefix


def main():
    parser = ArgumentParser()
    parser.add_argument("prefix", nargs='?', help="prefix")
    hwsuite.add_logging_options(parser)
    parser.add_argument("--project-root", metavar="DIR")
    parser.add_argument("--stage-dir", metavar="DIR", help="destination directory")
    args = parser.parse_args()
    try:
        hwsuite.configure_logging(args)
        proj_root = os.path.abspath(args.project_root or hwsuite.find_proj_root())
        cfg = hwsuite.get_config(proj_root)
        prefix = args.prefix
        if prefix is None:
            prefix = require_prefix(cfg, proj_root)
        stager = Stager(proj_root)
        num_staged = stager.stage(prefix, args.stage_dir)
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
    if num_staged == 0:
        # warning message already printed by logger
        return 1
    return 0
