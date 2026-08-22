#!/usr/bin/env bash

set -e
set -x

ruff check .
python -m py_compile app/model_qualification_runner.py
mypy .
ty check app
