#!/usr/bin/env python3
import json
import logging
import os
import sys

_log = logging.getLogger(__name__)

ENV_LOG_LEVEL = 'UNIT_TEST_LOG_LEVEL'

_logging_configured = False


def _parse_log_level(level_str: str):
    log_level = None
    if level_str:
        try:
            log_level = logging.__dict__[level_str]
        except KeyError:
            print(f"{ENV_LOG_LEVEL}={level_str} is not a valid log level", file=sys.stderr)
    return log_level or logging.INFO



def configure_logging():
    global _logging_configured
    if _logging_configured:
        return
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    cfg = {}
    env_val = os.getenv(ENV_LOG_LEVEL)
    cfg['log_level'] = env_val
    if os.path.exists(config_file):
        with open(config_file, 'r') as ifile:
            cfg.update(json.load(ifile))
    log_level_str = cfg.get('log_level', 'INFO')
    log_level = _parse_log_level(log_level_str)
    logging.basicConfig(level=log_level)
    _logging_configured = True
