"""``python -m opentcad ...`` — same as the ``opentcad`` command."""
import sys

from opentcad.cli import main

sys.exit(main())
