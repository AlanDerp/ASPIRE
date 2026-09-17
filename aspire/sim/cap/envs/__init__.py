# SPDX-FileCopyrightText: Copyright (c) 2026 Max Fu
# SPDX-License-Identifier: MIT
#
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Re-export when the optional simulation runtime is installed. Lightweight
# protocol/trace tooling under this package remains importable in the base
# repository environment.
try:
    from .base import BaseEnv, get_env, list_envs, register_env
    from . import simulators  # noqa: F401 -- triggers env registrations
except ModuleNotFoundError as error:
    if error.name != "gymnasium":
        raise

    __all__: list[str] = []
else:
    __all__ = ["BaseEnv", "get_env", "list_envs", "register_env"]
