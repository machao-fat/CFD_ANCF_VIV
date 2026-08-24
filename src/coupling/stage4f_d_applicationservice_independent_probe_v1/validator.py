from __future__ import annotations
def validate(e):
    # Script-authored booleans, MATLAB return codes and GUI/license state are never service evidence.
    independent = e.get('independent_response') is True or e.get('independent_process') is True or e.get('independent_event') is True
    return independent and e.get('request_id') == e.get('response_id') and e.get('response_payload_hash') and e.get('time_aligned') is True
def classify(e):
    return 'service_probe_unavailable' if not validate(e) else 'independent_service_evidence_verified'
