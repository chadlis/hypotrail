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
