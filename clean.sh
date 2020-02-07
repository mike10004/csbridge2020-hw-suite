#!/bin/bash

set -e

find . -type d -name "cmake-build*" -print -exec rm -r {} \+
find . -type f -name "screenlog.*" -delete
rm -rf "stage"

