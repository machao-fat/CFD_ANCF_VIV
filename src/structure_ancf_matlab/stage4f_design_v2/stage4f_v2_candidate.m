function candidate = stage4f_v2_candidate(c,mass_ratio,beta)
%STAGE4F_V2_CANDIDATE Full EB/ANCF modal, mesh and static evidence.
[T,rootAudit] = stage4f_v2_inverse_tension(c,mass_ratio,beta);
m_s = mass_ratio*c.m_f;
m_eff = m_s+c.m_added;
EI = beta*T*c.L^2;
E = EI/c.I;
EA = E*c.A;
candidate.mass_ratio = mass_ratio;
candidate.beta = beta;
candidate.m_f_kgpm = c.m_f;
candidate.m_s_kgpm = m_s;
candidate.m_added_kgpm = c.m_added;
candidate.m_eff_kgpm = m_eff;
candidate.equivalent_structure_density_kgpm3 = m_s/c.A;
candidate.top_tension_N = T;
candidate.EI_Nm2 = EI;
candidate.E_Pa = E;
candidate.EA_N = EA;
candidate.T_over_EA = T/EA;
candidate.inverse_root = rootAudit;
candidate.mass_matrix_construction = ['EB: consistent Hermite wet mass m_eff; ANCF: core consistent ', ...
    'M_structure plus transverse consistent M_added; no empirical dry-frequency scaling'];

mesh = repmat(struct(),numel(c.n_elem),1);
workingEB = cell(numel(c.n_elem),1);
workingANCF = cell(numel(c.n_elem),1);
for im = 1:numel(c.n_elem)
    nElem = c.n_elem(im);
    ebModel = stage4f_v2_build_eb(c,mass_ratio,beta,T,nElem,9);
    ebModal = stage4f_v2_modal_eb(ebModel,4);
    checkpoint = fullfile(c.result_dir,sprintf('ancf_checkpoint_mstar%d_beta_%s_nElem%d.mat', ...
        mass_ratio,strrep(sprintf('%.3g',beta),'.','p'),nElem));
    [ancfState,Mwet] = stage4f_v2_build_ancf(c,mass_ratio,beta,T,nElem,9);
    ancfModal = stage4f_v2_modal_ancf(ancfState,Mwet,4);
    crossMac = stage4f_v2_mac(ebModal.mode_shape,ancfModal.mode_shape);
    freqDifference = abs(ancfModal.frequency_Hz-ebModal.frequency_Hz)./ebModal.frequency_Hz;
    staticAudit = stage4f_v2_static_metrics(ancfState,T,EA,checkpoint);
    mesh(im).nElem = nElem;
    mesh(im).eb = stage4f_v2_export_modal(ebModal);
    mesh(im).ancf = stage4f_v2_export_modal(ancfModal);
    mesh(im).cross_MAC = crossMac;
    mesh(im).relative_frequency_difference = freqDifference;
    mesh(im).static = staticAudit;
    workingEB{im} = ebModal;
    workingANCF{im} = ancfModal;
end
candidate.meshes = mesh;
idx16 = find(c.n_elem==16,1); idx32 = find(c.n_elem==32,1);
candidate.mesh_convergence.nElem_pair = [16,32];
candidate.mesh_convergence.eb_relative_frequency_change = ...
    abs(mesh(idx16).eb.frequency_Hz-mesh(idx32).eb.frequency_Hz)./mesh(idx32).eb.frequency_Hz;
candidate.mesh_convergence.ancf_relative_frequency_change = ...
    abs(mesh(idx16).ancf.frequency_Hz-mesh(idx32).ancf.frequency_Hz)./mesh(idx32).ancf.frequency_Hz;
candidate.mesh_convergence.eb_MAC = stage4f_v2_mac(workingEB{idx16}.mode_shape,workingEB{idx32}.mode_shape);
candidate.mesh_convergence.ancf_MAC = stage4f_v2_mac(workingANCF{idx16}.mode_shape,workingANCF{idx32}.mode_shape);
candidate.target.eb_relative_error = abs(mesh(idx32).eb.frequency_Hz(1)-c.f_target)/c.f_target;
candidate.target.ancf_relative_error = abs(mesh(idx32).ancf.frequency_Hz(1)-c.f_target)/c.f_target;
candidate.target.Ur1_EB = c.U/(mesh(idx32).eb.frequency_Hz(1)*c.D);
candidate.target.Ur1_ANCF = c.U/(mesh(idx32).ancf.frequency_Hz(1)*c.D);
candidate.gates.beta_and_strain = candidate.T_over_EA <= 0.01;
candidate.gates.positive_finite_parameters = all(isfinite([T,EI,E,EA])) && all([T,EI,E,EA] > 0);
candidate.gates.target_frequency = candidate.target.eb_relative_error <= 0.01 && candidate.target.ancf_relative_error <= 0.01;
candidate.gates.Ur_range = candidate.target.Ur1_EB >= 5 && candidate.target.Ur1_EB <= 6 && ...
    candidate.target.Ur1_ANCF >= 5 && candidate.target.Ur1_ANCF <= 6;
candidate.gates.ancf_eb_first_frequency = mesh(idx32).relative_frequency_difference(1) <= 0.02;
candidate.gates.cross_MAC = all(mesh(idx32).cross_MAC >= 0.99);
candidate.gates.mesh_first_frequency = candidate.mesh_convergence.eb_relative_frequency_change(1) <= 0.01 && ...
    candidate.mesh_convergence.ancf_relative_frequency_change(1) <= 0.01;
candidate.gates.mesh_MAC = all(candidate.mesh_convergence.eb_MAC >= 0.99) && ...
    all(candidate.mesh_convergence.ancf_MAC >= 0.99);
candidate.gates.eigensystem = max([mesh(idx32).eb.eigen_residual;mesh(idx32).ancf.eigen_residual]) <= 1e-8 && ...
    mesh(idx32).eb.mass_orthogonality_inf <= 1e-8 && mesh(idx32).ancf.mass_orthogonality_inf <= 1e-8;
candidate.gates.static = mesh(idx32).static.passes;
gateValues = struct2cell(candidate.gates);
candidate.passes_pre_synthetic = all(cellfun(@(x) logical(x),gateValues));
end

