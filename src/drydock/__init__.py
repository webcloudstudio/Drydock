"""Drydock — governed Blueprint-driven software delivery."""

import logging

__version__ = "0.1.6"
__copyright__ = "Copyright (c) 2026 Web Cloud Studio. All rights reserved."

# Library hygiene: emit nothing unless a host application configures handlers.
# Per-execution loggers (drydock.execution.*) attach their own handlers and do
# not propagate, so this does not interfere with command-time logging.
logging.getLogger("drydock").addHandler(logging.NullHandler())
