#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .venv/.participant-installed ]; then
  echo 'Preparing the first local installation. This step requires internet; normal operation does not.'
  ./install.sh
fi
exec .venv/bin/python -m participant.server "$@"
