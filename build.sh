#!/bin/bash

set -e

CMAKE="${CMAKE:-cmake}"
MAKE="${MAKE:-make}"

command -V "$CMAKE"
command -V "$MAKE"

THIS_DIR=$(dirname "$0")
BUILD_DIR="${THIS_DIR}/cmake-build-debug"

"$CMAKE" -DCMAKE_BUILD_TYPE=Debug -S "${THIS_DIR}" -B "${BUILD_DIR}"

pushd "${BUILD_DIR}" >/dev/null

"$MAKE"

popd >/dev/null
