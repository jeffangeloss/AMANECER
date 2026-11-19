#!/usr/bin/env bash
# Ciclo completo de Blackboard. Uso: ./bb-todo.sh  (mismos argumentos que bb_todo.py)
cd "$(dirname "$0")"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" bb_todo.py "$@"
