function out = stage4f_v2_export_modal(modal)
%STAGE4F_V2_EXPORT_MODAL Remove working matrices while retaining evidence.
out.frequency_Hz = modal.frequency_Hz;
out.lambda_rad2ps2 = modal.lambda_rad2ps2;
out.mass_orthogonality_inf = modal.mass_orthogonality_inf;
out.eigen_residual = modal.eigen_residual;
out.stiffness_condition_number = modal.stiffness_condition_number;
out.mass_condition_number = modal.mass_condition_number;
out.sample_s_m = modal.sample_s_m;
out.mode_shape = modal.mode_shape;
out.maximum_sample_displacement_per_mass_normalized_coordinate = ...
    modal.maximum_sample_displacement_per_mass_normalized_coordinate;
end
