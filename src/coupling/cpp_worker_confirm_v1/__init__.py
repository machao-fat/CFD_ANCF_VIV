"""Independent bounded coordinator for the C++ worker confirm stage."""

from .coordinator import run_mock_confirm
from .cpp_adapter import CppKernelCampaignAdapter, CppAdapterError
from .real_slice_adapter import PersistentOpenFOAMSliceAdapter, RealSliceAdapterError
from .barrier import Stage100SliceBarrier
from .lifecycle import LifecycleError, ResidentCppWorkerLifecycle
from .envelope import MotionEnvelope, SCHEMA_VERSION as ENVELOPE_SCHEMA_VERSION, load_envelope, payload_hash

__all__ = ["run_mock_confirm", "CppKernelCampaignAdapter", "CppAdapterError",
           "PersistentOpenFOAMSliceAdapter", "RealSliceAdapterError", "Stage100SliceBarrier",
           "LifecycleError", "ResidentCppWorkerLifecycle", "MotionEnvelope",
           "ENVELOPE_SCHEMA_VERSION", "load_envelope", "payload_hash"]
