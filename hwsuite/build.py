#!/usr/bin/env python3
import os
from argparse import ArgumentParser
import sys
import subprocess
from subprocess import PIPE
from typing import Any, Dict

import hwsuite
from hwsuite import CommandException
import logging


_log = logging.getLogger(__name__)
_DEFAULT_CMAKE = 'cmake'
_DEFAULT_MAKE = 'make'


class Builder(object):

    def __init__(self, cmake:str=_DEFAULT_CMAKE):
        self.cmake = cmake

    def build(self, source_dir, build_dir, build_type='Debug', target_name=None):
        self.do_cmake_magic(source_dir, build_dir, build_type)
        if target_name is None:
            target_name = 'all'
        self.do_make(build_dir, target_name)

    def do_cmake_magic(self, source_dir, build_dir, build_type):
        proc = subprocess.run([self.cmake, '-DCMAKE_BUILD_TYPE=' + build_type, '-S', source_dir, '-B', build_dir], stdout=PIPE, stderr=PIPE)
        self.check_proc(proc)
        _log.debug("build complete in %s", source_dir)

    def check_proc(self, proc: subprocess.CompletedProcess):
        if proc.returncode != 0:
            raise CommandException.from_proc(proc)

    def do_make(self, build_dir, target_name):
        cmd = [self.cmake, '--build', build_dir, '--target', target_name, '--', '-j', '2']
        _log.debug("cmake second stage: %s", cmd)
        proc = subprocess.run(args=cmd, stdout=PIPE, stderr=PIPE)
        self.check_proc(proc)
        _log.debug("make complete in %s", build_dir)

    @staticmethod
    def from_config(cfg: Dict[str, Any]) -> 'Builder':
        cmake = hwsuite.resolve_executable('cmake', cfg)
        return Builder(cmake)


def build(proj_root, build_dir=None, builder=None, build_type='Debug', cfg=None):
    #  "$CMAKE" -DCMAKE_BUILD_TYPE=Debug -S "${THIS_DIR}" -B "${BUILD_DIR}"
    if cfg is None:
        cfg = hwsuite.get_config(proj_root=proj_root)
    source_dir = proj_root
    build_dir = build_dir or os.path.join(source_dir, hwsuite.BUILD_DIR_BASENAME)
    if builder is None:
        builder = Builder.from_config(cfg)
    builder.build(source_dir, build_dir, build_type=build_type)


def main():
    parser = ArgumentParser()
    hwsuite.add_logging_options(parser)
    parser.add_argument("source_root", nargs='?')
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    try:
        proj_root = hwsuite.find_proj_root()
        source_dir = args.source_root or proj_root
        build(source_dir)
        return 0
    except hwsuite.MessageworthyException as ex:
        print(f"{__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
