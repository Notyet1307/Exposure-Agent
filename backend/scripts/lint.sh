#!/usr/bin/env bash

set -e
set -x

ruff check .
python -m py_compile app/domain/model_qualification.py app/model_qualification_runner.py \
  app/domain/ai_governance_drafts.py app/ai_draft_runner.py
mypy .
ty check app
