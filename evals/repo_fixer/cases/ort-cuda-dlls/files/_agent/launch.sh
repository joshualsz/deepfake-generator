#!/usr/bin/env bash
# Launch wrapper. The agent may change this file; app.py is the repo's own code.
cd "$(dirname "$0")/.."
.venv/Scripts/python app.py
