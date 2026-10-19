"""No-console portable entry; all runtime state is created after root selection."""

import sys
from multiprocessing import freeze_support

sys.dont_write_bytecode = True
freeze_support()

from fittrack.cli import main  # noqa: E402

raise SystemExit(main())
