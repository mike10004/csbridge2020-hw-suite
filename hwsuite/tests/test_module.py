#!/usr/bin/env python3
import os
import tempfile
from pathlib import Path
from unittest import TestCase
import hwsuite
import hwsuite.init


class ModuleMethodsTest(TestCase):

    def test_find_proj_root_bad(self):
        with tempfile.TemporaryDirectory() as tempdir:
            try:
                hwsuite.find_proj_root(cwd=tempdir)
                self.fail("should have failed")
            except hwsuite.WhereamiException:
                pass

    def test_find_proj_root_standard(self):
        with tempfile.TemporaryDirectory() as tempdir:
            hwsuite.init.do_init(tempdir, 'unittest-example', safety_mode='abort')
            actual = hwsuite.find_proj_root(cwd=tempdir)
            self.assertEqual(tempdir, actual)

    def test_find_proj_root_child(self):
        with tempfile.TemporaryDirectory() as tempdir:
            hwsuite.init.do_init(tempdir, 'unittest-example', safety_mode='abort')
            subdir = os.path.join(tempdir, "q1")
            os.makedirs(subdir)
            actual = hwsuite.find_proj_root(cwd=subdir)
            self.assertEqual(tempdir, actual)

    def test_store_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            proj_root = tempdir
            hwsuite.init.do_init(proj_root, 'unittest-example', safety_mode='abort')
            cfg = hwsuite.get_config(proj_root=proj_root)
            cfg['foo'] = 'bar'
            hwsuite.store_config(cfg, proj_root=proj_root)
            cfg = hwsuite.get_config(proj_root=proj_root)
            self.assertDictEqual({'foo': 'bar'}, cfg)

    def test_describe_path(self):
        test_cases = [
            (os.path.join(os.getcwd(), 'foo'), None, False, 'foo'),
            ('/a/b/c', '/a/b', False, 'c'),
            ('/a/b/c', '/d/e/f', False, '/a/b/c'),
            ('/a/b/c', '/a/b/c', True, 'current directory'),
            ('/a/b/c', '/a/b/c', False, '.',)
        ]
        for pathname, start, decorate, expected in test_cases:
            with self.subTest():
                actual = hwsuite.describe_path(pathname, start, decorate=decorate)
                self.assertEqual(expected, actual, f"expect describe_path({repr(pathname)}, {repr(start)}, {repr(decorate)} = {repr(expected)} but it is {repr(actual)}")