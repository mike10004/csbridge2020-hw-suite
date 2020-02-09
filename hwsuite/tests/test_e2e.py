#!/usr/bin/env python3
import os
import tempfile
from unittest import TestCase
import json
import hwsuite.init
import hwsuite.question
import hwsuite.check
from argparse import Namespace
from hwsuite.tests.test_check import _create_namespace as _create_check_namespace


class EndToEndTest(TestCase):

    def _define_test_cases(self, q_dir: str, test_cases_def: dict):
        with open(os.path.join(q_dir, 'test-cases.json'), 'w') as ofile:
            json.dump(test_cases_def, ofile, indent=2)

    def _write_cpp(self, q_dir: str, source_code: str):
        with open(os.path.join(q_dir, 'main.cpp'), 'w') as ofile:
            ofile.write(source_code)

    def test_do_homework(self):
        with tempfile.TemporaryDirectory() as tempdir:
            proj_dir = os.path.join(tempdir, 'hw-example')
            os.makedirs(proj_dir)
            hwsuite.init.do_init(proj_dir, 'hw_example', safety_mode='ignore')
            q_args = Namespace(project_dir=proj_dir, name=None, mode='safe')
            ecode = hwsuite.question._main(q_args)
            self.assertEqual(0, ecode, "question exit code")
            q1_dir = os.path.join(proj_dir, 'q1')
            self.assertTrue(os.path.isdir(q1_dir))
            self._write_cpp(q1_dir, """\
#include <iostream>
using namespace std;
int main() {
    int a, b;
    cout << "Enter two numbers: ";
    cin >> a;
    cin >> b;
    cout << "Sum = " << (a + b) << endl;
    return 0;
}
""")
            self._define_test_cases(q1_dir, {
                'input': "{a} {b}\n",
                'expected': "Enter two numbers: {a} {b}\nSum = {c}\n",
                'param_names': ['a', 'b', 'c'],
                'test_cases': [
                    [1, 2, 3],
                    [2, 2, 4],
                    [-4, 1, -3],
                ]
            })
            check_args = _create_check_namespace(project_dir=proj_dir, subdirs=[], report='repr', await=True)
            ecode = hwsuite.check._main(check_args)
            self.assertEqual(0, ecode, "check exit code")
            ecode = hwsuite.question._main(q_args)
            self.assertEqual(0, ecode, "question exit code (second time)")
            q2_dir = os.path.join(proj_dir, 'q2')
            self.assertTrue(os.path.isdir(q2_dir), "expect q2 exists")
            self._write_cpp(q2_dir, """\
#include <iostream>
using namespace std;
int main() {
    int x;
    cout << "Enter integer: ";
    cin >> x;
    cout << "Square = " << (x * x) << endl;
    return 0;
}
""")
            self._define_test_cases(q2_dir, {
                'input': "{x}\n",
                'expected': "Enter integer: {x}\nSquare = {y}\n",
                'param_names': ['x', 'y'],
                'test_cases': [
                    [0, 0],
                    [1, 1],
                    [-1, 1],
                    [4, 16],
                ]
            })
            ecode = hwsuite.check._main(check_args)
            self.assertEqual(0, ecode, "check exit code (second time)")

