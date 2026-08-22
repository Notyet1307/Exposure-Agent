#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
exec .venv/bin/python tests/model_qualification_fixture/verify.py
