#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

python -m alembic upgrade head
exec python -m tracker.app
