#!/bin/sh
set -eu
ip link set lo up
python3 -c "import socket; s=socket.socket(); s.settimeout(1); result=s.connect_ex(('1.1.1.1',443)); s.close(); assert result != 0, 'External networking must be disabled'"
export PYTHONPATH="$PWD/tests/offline_guard:$PWD"
export PARTICIPANT_TEST_PYTHON="$PWD/.venv/bin/python"
.venv/bin/python -m contracts.offline_bundle.v1.selftest
.venv/bin/python -m unittest discover -s tests -v
npx --offline playwright test
