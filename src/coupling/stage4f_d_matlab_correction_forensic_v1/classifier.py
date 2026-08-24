from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import math

class FailureClass(str, Enum):
    AUTHORIZATION = "authorization_network_service"
    INPUT = "input_artifact"
    OUTPUT = "output_artifact"
    TRANSACTION = "transaction_identity"
    NUMERICAL = "numerical_nonfinite_or_error"
    TIMEOUT = "orchestration_timeout"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class CorrectionEvidence:
    return_code: int
    output_exists: bool = True
    output_hash_ok: bool = True
    identity_ok: bool = True
    finite: bool = True
    timeout: bool = False
    worker_license: bool | None = None
    application_service: bool | None = None
    network_error: bool = False
    numerical_error: bool = False

def classify(e: CorrectionEvidence) -> FailureClass:
    if e.return_code != 0:
        if e.timeout: return FailureClass.TIMEOUT
        if e.numerical_error or not e.finite: return FailureClass.NUMERICAL
        if e.worker_license is False or e.application_service is False:
            return FailureClass.AUTHORIZATION
        if e.identity_ok is False: return FailureClass.TRANSACTION
        if e.network_error and e.worker_license is False:
            return FailureClass.AUTHORIZATION
        return FailureClass.UNKNOWN
    if not e.output_exists or not e.output_hash_ok: return FailureClass.OUTPUT
    if not e.identity_ok: return FailureClass.TRANSACTION
    if not e.finite: return FailureClass.NUMERICAL
    return FailureClass.UNKNOWN

def finite_values(values):
    return all(math.isfinite(float(v)) for v in values)
