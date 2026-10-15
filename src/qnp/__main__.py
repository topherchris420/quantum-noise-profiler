"""Support python -m qnp as well as the installed qnp command."""

from .cli import main

raise SystemExit(main())
