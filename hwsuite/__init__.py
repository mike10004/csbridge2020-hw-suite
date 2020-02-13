#!/usr/bin/env python3

import argparse
import json
import logging
import os
import os.path
import subprocess

_log = logging.getLogger(__name__)
CFG_FILENAME = ".hwconfig.json"
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


class CommandException(Exception):

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
    prev_dir = None
    while not os.path.exists(os.path.join(proj_root, cfg_filename)) and proj_root != '/' and prev_dir != proj_root:
        prev_dir = proj_root
        proj_root = os.path.dirname(proj_root)
    if os.path.exists(os.path.join(proj_root, cfg_filename)):
        return proj_root
    # TODO allow for use programs copied into proj dir
    raise WhereamiException("this directory is not an ancestor of a hw project; use hwinit to establish a project directory")


def _load_config(cfg_pathname=None, default_cfg_filename=CFG_FILENAME, proj_root=None):
    if cfg_pathname is None:
        proj_root = proj_root or find_proj_root()
        cfg_pathname = os.path.join(proj_root, default_cfg_filename)
    with open(cfg_pathname, 'r') as ifile:
        ifile_str = ifile.read()
    if not ifile_str.strip():
        return {}
    return json.loads(ifile_str)


def get_config(cfg_pathname=None, proj_root=None):
    try:
        return _CACHE[_KEY_CFG]
    except KeyError:
        config = _load_config(cfg_pathname, proj_root=proj_root)
        _CACHE[_KEY_CFG] = config
        return config


def store_config(cfg=None, cfg_pathname=None, default_cfg_filename=CFG_FILENAME, proj_root=None):
    cfg = cfg if cfg is not None else get_config(cfg_pathname, proj_root=proj_root)
    cfg_pathname = cfg_pathname or os.path.join(proj_root or find_proj_root(), default_cfg_filename)
    with open(cfg_pathname, 'w') as ofile:
        json.dump(cfg, ofile, indent=2)


def configure_logging(args: argparse.Namespace):
    logging.basicConfig(level=logging.__dict__[args.log_level])


def add_logging_options(parser: argparse.ArgumentParser):
    parser.add_argument("-l", "--log-level", metavar="LEVEL", choices=_LOG_LEVEL_CHOICES, default='INFO',
                        help=f"set log level to one of {_LOG_LEVEL_CHOICES}")


def describe_path(pathname):
    relpath = os.path.relpath(pathname)
    abspath = os.path.abspath(pathname)
    return relpath if len(relpath) < len(abspath) else abspath


def resolve_executable(exec_name, cfg: dict):
    val = cfg.get('executables', {}).get(exec_name, None)
    return val if val else exec_name