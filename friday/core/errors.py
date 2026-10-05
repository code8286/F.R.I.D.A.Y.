# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Typed errors shared across FRIDAY. Catch these, never bare Exception, in control flow."""

from __future__ import annotations


class FridayError(Exception):
    """Base class for all FRIDAY errors."""


# ---- config / storage -------------------------------------------------------
class ConfigError(FridayError):
    pass


class StorageError(FridayError):
    pass


class SecretStoreUnavailable(FridayError):
    """No writable secret store (the OS keyring) is available, or it refused the operation."""


class AuditIntegrityError(FridayError):
    """The audit hash chain does not verify."""


# ---- control ----------------------------------------------------------------
class KillSwitchTripped(FridayError):
    """The kill switch is engaged; all agent work must stop."""


class AdmissionError(FridayError):
    """An input origin is not allowed to talk to FRIDAY."""


# ---- tools ------------------------------------------------------------------
class ToolError(FridayError):
    """A tool failed in an expected way. The message is safe to show the model."""


class UnknownToolError(ToolError):
    pass


class ToolArgumentError(ToolError):
    pass


class PolicyDenied(FridayError):
    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        super().__init__(message)
        self.reasons = reasons


class ConfirmationError(FridayError):
    pass


# ---- providers --------------------------------------------------------------
class ProviderError(FridayError):
    """Base for LLM provider failures. `retryable` drives the loop's backoff."""

    retryable = False


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderRateLimited(ProviderError):
    retryable = True

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderServerError(ProviderError):
    retryable = True


class ProviderConnectionError(ProviderError):
    retryable = True


class ProviderAuthError(ProviderError):
    retryable = False


class ProviderBadRequest(ProviderError):
    retryable = False


class ProviderProtocolError(ProviderError):
    """Reply could not be parsed into the canonical format (also used by the JSON tool protocol)."""

    retryable = False
