#!/usr/bin/env python3

import argparse
import json
import logging
import os
import os.path
import subprocess
from subprocess import PIPE
from typing import Tuple, Sequence

_log = logging.getLogger(__name__)
CFG_FILENAME = ".hwconfig.json"
CFG_CACHE_DISABLED = False
_CACHE = {}
_KEY_CFG = 'config'
BUILD_DIR_BASENAME = 'cmake-build-debug'
_LOG_LEVEL_CHOICES = ('DEBUG', 'INFO', 'WARNING', 'ERROR')


class MessageworthyException(Exception):
    """Exception superclass for exceptions that should programs should handle by
    producing an informative error message and terminating.

    This type is for errors that are of the sort that a user can react to and resolve,
    such as providing malformed input, as opposed to unexpected states that likely
    indicate program bugs.
    """
    pass


class WhereamiException(MessageworthyException):
    pass


class CommandException(MessageworthyException):

    pass

    @staticmethod
    def from_proc(proc: subprocess.CompletedProcess, cmd='command', charset='utf8') -> 'CommandException':
        # stdout = '' if proc.stdout is None else proc.stdout.decode(charset)[:256]  # TODO do something with this stdout
        stderr = '' if proc.stderr is None else proc.stderr.decode(charset)[:256]
        msg = f"nonzero exit {proc.returncode} from {cmd}; stderr={stderr}"
        return CommandException(msg)


def _cmd(cmd_list, err_msg="Command Line Error", allow_nonzero_exit=False) -> str:
    proc = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if allow_nonzero_exit or proc.returncode != 0:
        raise CommandException("exit code {}; {}\n{}".format(proc.returncode, err_msg, proc.stderr.decode('utf8')))
    return proc.stdout.decode('utf8')


def find_proj_root(cwd=None, cfg_filename=CFG_FILENAME):
    cwd = os.path.abspath(cwd or os.getcwd())
    proj_root = cwd
    while not os.path.exists(os.path.join(proj_root, cfg_filename)) and proj_root != '/':
        proj_root = os.path.dirname(proj_root)
    if os.path.exists(os.path.join(proj_root, cfg_filename)):
        return proj_root
    # TODO allow for use programs copied into proj dir
    raise WhereamiException("no ancestor is a hw project root; use hwinit to establish a project directory")


def _load_config_from_file(cfg_pathname=None, default_cfg_filename=CFG_FILENAME, proj_root=None) -> Tuple[dict, str]:
    if cfg_pathname is None:
        proj_root = proj_root or find_proj_root()
        cfg_pathname = os.path.join(proj_root, default_cfg_filename)
    with open(cfg_pathname, 'r') as ifile:
        ifile_str = ifile.read()
    if not ifile_str.strip():
        return {}, cfg_pathname
    return json.loads(ifile_str), cfg_pathname


def get_config(proj_root, cfg_pathname=None) -> dict:
    assert proj_root, "proj_root must be specified"
    if CFG_CACHE_DISABLED:
        return _load_config_from_file(cfg_pathname, proj_root=proj_root)[0]
    try:
        return _CACHE[_KEY_CFG][proj_root]
    except KeyError:
        config, cfg_pathname = _load_config_from_file(cfg_pathname, proj_root=proj_root)
        cfgs = _CACHE.get(_KEY_CFG, None)
        if cfgs is None:
            cfgs = {}
            _CACHE[_KEY_CFG] = cfgs
        cfgs[cfg_pathname] = config
        return config


def store_config(cfg=None, cfg_pathname=None, default_cfg_filename=CFG_FILENAME, proj_root=None):
    cfg = cfg if cfg is not None else get_config(proj_root, cfg_pathname)
    cfg_pathname = cfg_pathname or os.path.join(proj_root or find_proj_root(), default_cfg_filename)
    with open(cfg_pathname, 'w') as ofile:
        json.dump(cfg, ofile, indent=2)


def configure_logging(args: argparse.Namespace):
    logging.basicConfig(level=logging.__dict__[args.log_level])


def add_logging_options(parser: argparse.ArgumentParser):
    parser.add_argument("-l", "--log-level", metavar="LEVEL", choices=_LOG_LEVEL_CHOICES, default='INFO',
                        help=f"set log level to one of {_LOG_LEVEL_CHOICES}")


def describe_path(pathname, cwd=None, decorate=False):
    relpath = os.path.relpath(pathname, start=cwd)
    abspath = os.path.abspath(pathname)
    if len(relpath) < len(abspath):
        if decorate and relpath == '.':
            return 'current directory'
        return relpath
    else:
        return abspath


class GitException(Exception):
    pass


class GitRunner(object):

    def __init__(self):
        self.executable = 'git'

    def run(self, args: Sequence[str]):
        cmd = [self.executable] + list(args)
        proc = subprocess.run(cmd, stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            _log.error("exit %s from git: %s", proc.returncode, proc.stderr.decode('utf8'))
            raise GitException(f"exit {proc.returncode} from git")
        return proc.stdout.decode('utf8')

