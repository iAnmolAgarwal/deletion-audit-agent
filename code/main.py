"""Entry point from a fresh unzip: ``python code/main.py --run-id <id> --set test``.

It puts ``code/`` on the path and hands the arguments to the deletion-audit CLI
(:func:`deletion_audit.__main__.main`); ``python code/main.py --help`` lists the commands.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deletion_audit.__main__ import main  # noqa: E402  (needs code/ on the path first)

if __name__ == "__main__":
    sys.exit(main())
