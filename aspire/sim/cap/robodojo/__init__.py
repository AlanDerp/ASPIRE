# SPDX-License-Identifier: Apache-2.0
"""ASPIRE-side RoboDojo adapter. Importing this package starts no services."""

from .policy import Model
from .protocol import RobotSpec, adapt_observation

__all__ = ["Model", "RobotSpec", "adapt_observation"]
