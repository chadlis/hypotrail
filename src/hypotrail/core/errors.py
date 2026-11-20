"""Errors that reach the command line, and the process exit codes.

Every error carries a machine-readable `code`, a human `message`, the `stage`
that failed and a `details` mapping that never holds a secret.
"""

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_INTEGRITY_REFUSED = 3
EXIT_INFRASTRUCTURE = 4
EXIT_CAPABILITY_UNAVAILABLE = 5
EXIT_LOCK_OR_CONFLICT = 6


class HypotrailError(Exception):
    exit_code = EXIT_INFRASTRUCTURE

    def __init__(self, code, message, *, stage, details=None, exit_code=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.details = dict(details or {})
        if exit_code is not None:
            self.exit_code = exit_code

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "details": self.details,
        }


class InvalidInputError(HypotrailError):
    exit_code = EXIT_INVALID_INPUT


class IntegrityError(HypotrailError):
    exit_code = EXIT_INTEGRITY_REFUSED


def coded_error(error: Exception) -> HypotrailError:
    """The coded error any exception stands for: a Hypotrail error as it is, any other exception by its type only.

    The text of a foreign exception can carry anything, a provider key included, so it is never reported: an OS error is
    `INFRASTRUCTURE_FAILURE` and anything else `UNEXPECTED_ERROR`, each with the exception's type in `details.type`.
    """
    if isinstance(error, HypotrailError):
        return error
    name = type(error).__name__
    if isinstance(error, OSError):
        return HypotrailError("INFRASTRUCTURE_FAILURE", name, stage="infrastructure", details={"type": name}, exit_code=EXIT_INFRASTRUCTURE)
    return HypotrailError("UNEXPECTED_ERROR", f"unexpected {name}", stage="infrastructure", details={"type": name}, exit_code=EXIT_INFRASTRUCTURE)
