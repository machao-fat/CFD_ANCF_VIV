import math

from src.coupling.online_file_coupling.energy_audit import compute_energy_rows
from src.coupling.online_file_coupling.continuous_fsi_driver import _stored_energy


def test_energy_audit_separates_predicted_corrected_work():
    rows = [
        {"step":"1", "time_s":"0.1", "force_x_N":"2", "force_y_N":"0", "force_z_N":"0",
         "predicted_vx_mps":"1", "predicted_vy_mps":"0", "predicted_vz_mps":"0",
         "corrected_vx_mps":"0.5", "corrected_vy_mps":"0", "corrected_vz_mps":"0",
         "damping_power_W":"0", "stored_energy_J":"0.1"},
        {"step":"2", "time_s":"0.2", "force_x_N":"2", "force_y_N":"0", "force_z_N":"0",
         "predicted_vx_mps":"1", "predicted_vy_mps":"0", "predicted_vz_mps":"0",
         "corrected_vx_mps":"0.5", "corrected_vy_mps":"0", "corrected_vz_mps":"0",
         "damping_power_W":"0", "stored_energy_J":"0.2"},
    ]
    audit, summary = compute_energy_rows(rows, initial_stored_energy_J=0.0)
    assert math.isclose(summary["W_CFD_J"], 0.4)
    assert math.isclose(summary["W_structure_J"], 0.2)
    assert math.isclose(summary["E_coupling_defect_J"], 0.2)
    assert math.isclose(summary["structure_energy_balance_residual_J"], 0.0)
    assert len(audit) == 2


def test_energy_audit_preserves_nonzero_initial_energy_and_explicit_window():
    rows = []
    for step in range(1, 5):
        rows.append({
            "step": str(step), "time_s": str(0.1*step),
            "force_representation": "integrated_N",
            "force_x_N": "1", "force_y_N": "0", "force_z_N": "0",
            "predicted_vx_mps": "1", "predicted_vy_mps": "0", "predicted_vz_mps": "0",
            "corrected_vx_mps": "1", "corrected_vy_mps": "0", "corrected_vz_mps": "0",
            "damping_power_W": "0", "stored_energy_J": str(10.0+0.1*step),
        })
    audit, summary = compute_energy_rows(
        rows, initial_stored_energy_J=10.0,
        window_start_s=0.2, window_end_s=0.4,
        steady_state_verified=True,
    )
    assert math.isclose(summary["stored_energy_change_J"], 0.4)
    assert math.isclose(summary["structure_energy_balance_residual_J"], 0.0, abs_tol=1.0e-14)
    assert math.isclose(summary["audit_window_W_structure_J"], 0.2)
    assert math.isclose(summary["audit_window_stored_energy_change_J"], 0.2)
    assert summary["physical_energy_acceptance_ready"] is True
    assert math.isclose(audit[0]["stored_energy_previous_J"], 10.0)


def test_energy_audit_legacy_fallback_is_not_physical_acceptance():
    rows = [{
        "step": "1", "time_s": "0.1", "force_x_N": "0", "force_y_N": "0", "force_z_N": "0",
        "predicted_vx_mps": "0", "predicted_vy_mps": "0", "predicted_vz_mps": "0",
        "corrected_vx_mps": "0", "corrected_vy_mps": "0", "corrected_vz_mps": "0",
        "damping_power_W": "0", "stored_energy_J": "5",
    }]
    _, summary = compute_energy_rows(rows)
    assert summary["initial_stored_energy_known"] is False
    assert summary["force_unit_verified_integrated_N"] is False
    assert summary["physical_energy_acceptance_ready"] is False


def test_energy_audit_rejects_distributed_force_units():
    rows = [{
        "step": "1", "time_s": "0.1", "force_representation": "distributed_Npm",
        "force_x_N": "1", "force_y_N": "0", "force_z_N": "0",
        "predicted_vx_mps": "0", "predicted_vy_mps": "0", "predicted_vz_mps": "0",
        "corrected_vx_mps": "0", "corrected_vy_mps": "0", "corrected_vz_mps": "0",
        "damping_power_W": "0", "stored_energy_J": "0",
    }]
    try:
        compute_energy_rows(rows)
    except ValueError as exc:
        assert "integrated_N" in str(exc)
    else:
        raise AssertionError("distributed force was accepted as an integrated interface force")


def test_online_driver_uses_complete_mechanical_energy_including_base_load_potential():
    energy = {
        "kinetic_energy_J": 1.0,
        "axial_strain_energy_J": 4.0,
        "external_potential_energy_J": -10.0,
        "mechanical_energy_J": -5.0,
    }
    assert math.isclose(_stored_energy(energy), -5.0)


def test_energy_audit_separates_load_projection_from_temporal_defect():
    rows = [{
        "step": "1", "time_s": "0.1", "force_representation": "integrated_N",
        "force_x_N": "2", "force_y_N": "3", "force_z_N": "0",
        "applied_force_x_N": "0", "applied_force_y_N": "3", "applied_force_z_N": "0",
        "predicted_vx_mps": "4", "predicted_vy_mps": "2", "predicted_vz_mps": "0",
        "corrected_vx_mps": "0", "corrected_vy_mps": "1", "corrected_vz_mps": "0",
        "damping_power_W": "0", "stored_energy_previous_J": "0", "stored_energy_J": "0.3",
    }]
    _, summary = compute_energy_rows(rows)
    # total: (2*4+3*2)-3*1 = 11 W; projection: 2*4=8 W;
    # predictor/corrector: 3*(2-1)=3 W, all integrated for 0.1 s.
    assert math.isclose(summary["E_coupling_defect_J"], 1.1)
    assert math.isclose(summary["E_load_projection_defect_J"], 0.8)
    assert math.isclose(summary["E_predictor_corrector_defect_J"], 0.3)
    assert math.isclose(summary["coupling_defect_decomposition_closure_J"], 0.0, abs_tol=1.0e-14)
