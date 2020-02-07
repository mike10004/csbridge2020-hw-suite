#!/usr/bin/env python3
import os
from argparse import ArgumentParser
import sys
import subprocess
from subprocess import PIPE
import hwsuite
from hwsuite import CommandException
import logging


_log = logging.getLogger(__name__)


class Builder(object):

    def __init__(self):
        self.cmake = 'cmake'
        self.make = 'make'

    def build(self, source_dir, build_dir, build_type='Debug'):
        self.do_cmake_magic(source_dir, build_dir, build_type)
        self.do_make(build_dir)

    def do_cmake_magic(self, source_dir, build_dir, build_type):
        proc = subprocess.run([self.cmake, '-DCMAKE_BUILD_TYPE=' + build_type, '-S', source_dir, '-B', build_dir], stdout=PIPE, stderr=PIPE)
        self.check_proc(proc)
        _log.debug("build complete in %s", source_dir)

    def check_proc(self, proc: subprocess.CompletedProcess):
        if proc.returncode != 0:
            raise CommandException.from_proc(proc)

    def do_make(self, build_dir):
        proc = subprocess.run([self.make], cwd=build_dir, stdout=PIPE, stderr=PIPE)
        self.check_proc(proc)
        _log.debug("make complete in %s", build_dir)


def build(proj_root, build_dir=None, builder=None, build_type='Debug'):
    #  "$CMAKE" -DCMAKE_BUILD_TYPE=Debug -S "${THIS_DIR}" -B "${BUILD_DIR}"
    source_dir = proj_root
    build_dir = build_dir or os.path.join(source_dir, hwsuite.BUILD_DIR_BASENAME)
    builder = builder or Builder()
    builder.build(source_dir, build_dir, build_type=build_type)


def main():
    parser = ArgumentParser()
    hwsuite.add_logging_options(parser)
    parser.add_argument("source_root", nargs='?')
    args = parser.parse_args()
    hwsuite.configure_logging(args)
    proj_root = hwsuite.find_proj_root()
    source_dir = args.source_root or proj_root
    build(source_dir)
    return 0
