"""Stage97 independent C++ worker and persistent IPC protocol."""

from .protocol import (
    FrameError,
    StepRequest,
    StepResponse,
    encode_request,
    decode_response,
    validate_response,
)

__all__ = ["FrameError", "StepRequest", "StepResponse", "encode_request", "decode_response", "validate_response"]
