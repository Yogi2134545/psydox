"""
Psydox Core — Centralized error hierarchy.

User-facing messages are clean and actionable.
Logs contain full technical detail.
Never expose stack traces or API internals to end users.
"""


class PsydoxError(Exception):
    """Base for all Psydox errors."""
    user_message: str = "Something went wrong. Please try again."
    log_detail:   str = ""

    def __init__(self, message: str = "", user_message: str = ""):
        super().__init__(message)
        self.log_detail   = message
        self.user_message = user_message or self.__class__.user_message


# ── AI errors ────────────────────────────────────────────────────────────────

class AIProviderError(PsydoxError):
    user_message = "The AI provider encountered an error. Please retry."


class AIQuotaError(AIProviderError):
    user_message = "AI quota exceeded. Please try again later or contact support."


class AIValidationError(PsydoxError):
    user_message = "The AI returned an unexpected result. Please retry."


class AIUnavailableError(AIProviderError):
    user_message = "AI is temporarily unavailable. Classic processing still works."


# ── Product errors ────────────────────────────────────────────────────────────

class ProductAnalysisError(PsydoxError):
    user_message = "Could not analyze the product image. Please try a clearer image."


# ── Quality errors ────────────────────────────────────────────────────────────

class QualityError(PsydoxError):
    user_message = "The generated image did not pass quality checks."


class FidelityError(QualityError):
    user_message = "The product looks different from the original. Regenerating..."


# ── Storage errors ────────────────────────────────────────────────────────────

class StorageError(PsydoxError):
    user_message = "Could not save or retrieve files. Please try again."


# ── Job errors ────────────────────────────────────────────────────────────────

class JobError(PsydoxError):
    user_message = "The job encountered an error. Check the results for details."


class JobNotFoundError(JobError):
    user_message = "Job not found."


# ── Auth errors ───────────────────────────────────────────────────────────────

class AuthenticationError(PsydoxError):
    user_message = "Invalid email or password."


class AuthorizationError(PsydoxError):
    user_message = "You don't have permission to perform this action."


# ── Feature errors ────────────────────────────────────────────────────────────

class FeatureNotFoundError(PsydoxError):
    user_message = "Feature not available."


class FeatureInputError(PsydoxError):
    user_message = "Invalid input. Please check your settings and try again."


class FeatureDisabledError(PsydoxError):
    user_message = "This feature is currently disabled."
