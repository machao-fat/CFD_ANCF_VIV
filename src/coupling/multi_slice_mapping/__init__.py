"""Stage-4A multi-slice schema, force mapping and virtual-work checks.

This package is intentionally independent from the stage-2/3 file-exchange
implementation.  It implements the Stage4-Multislice Draft 2 candidate
schema (0.2.1) and refuses legacy schemas instead of silently adapting them.
"""

from .mapping import *  # noqa: F401,F403
