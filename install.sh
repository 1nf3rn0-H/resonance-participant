#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null 2>&1 || { echo 'Install Python 3.11 or later first.' >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo 'Install Node.js 22.18 or later first.' >&2; exit 1; }
node -e "const [a,b]=process.versions.node.split('.').map(Number);if(a<22||(a===22&&b<18))process.exit(1)" || { echo 'Node.js 22.18 or later is required.' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or later is required"'
if [ ! -f .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m contracts.offline_bundle.v1.selftest
.venv/bin/python -c "from participant.sampling import verify_native; verify_native()"
touch .venv/.participant-installed
printf 'Installation verified. You can now disconnect from the internet and run ./start.sh\n'
