#!/usr/bin/env bash

set -e
set -x

ruff check .
mypy .
ty check app
