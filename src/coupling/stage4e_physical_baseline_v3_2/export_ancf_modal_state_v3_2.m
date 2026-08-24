function audit = export_ancf_modal_state_v3_2(output_dir)
%EXPORT_ANCF_MODAL_STATE_V3_2 Read-only ANCF modal-state exporter.
%
% This standalone exporter repeats the existing Stage 4E baseline model
% construction and retains the eigenvectors that the older report discarded.
% It does not modify any production MATLAB function and never starts CFD.

if nargin < 1 || isempty(output_dir)
    error('export_ancf_modal_state_v3_2:Output', 'An output directory is required.');
end
if ~exist(output_dir, 'dir')
    mkdir(output_dir);
end

this_file = mfilename('fullpath');
this_dir = fileparts(this_file);
project_root = fileparts(fileparts(fileparts(this_dir)));
ancf_dir = fullfile(project_root, 'src', 'structure_ancf_matlab');
addpath(ancf_dir);

L = 7.64; D = 0.02841; dInner = 0.025;
mass_per_length = 1.24; EI = 58.6; EA = 9.4e5;
top_tension = 980.0; fluid_rho = 1000.0;
gravity = false; buoyancy = false; damping_alpha = 0.0; damping_beta = 0.0;
n_elem_values = [8, 16];

audit = struct();
audit.schema_version = '0.2.1';
audit.status = 'completed_read_only_modal_export';
audit.openfoam_started = false;
audit.read_only_core = true;
audit.export_script = this_file;
audit.matlab_version = version;
audit.dof_index_base = 'MATLAB 1-based in MAT/JSON audit; Python adapters must explicitly convert to 0-based';
audit.node_dof_order = '[position_x,position_y,position_z,slope_x,slope_y,slope_z]';
audit.parameters = struct('L_m',L,'D_m',D,'dInner_m',dInner, ...
    'mass_per_length_kgpm',mass_per_length,'EI_Nm2',EI,'EA_N',EA, ...
    'top_tension_N',top_tension,'fluid_rho_kgpm3',fluid_rho, ...
    'gravity',gravity,'buoyancy',buoyancy,'damping_alpha',damping_alpha, ...
    'damping_beta',damping_beta,'nElem_values',n_elem_values);
audit.cases = cell(numel(n_elem_values),1);

for ic = 1:numel(n_elem_values)
    ne = n_elem_values(ic);
    model = vertical_ttr_case('L',L,'D',D,'dInner',dInner, ...
        'nElem',ne,'nSlices',3,'topTension_N',top_tension, ...
        'youngs_modulus_Pa',2.07e11,'dt',1.0e-3);
    model.material.rho = mass_per_length / model.material.area;
    model.material.EA = EA;
    model.material.EI = EI;
    model.fluid.rho = fluid_rho;
    model.physics.include_gravity = gravity;
    model.physics.include_buoyancy = buoyancy;
    model.static.external_slice_force_N = zeros(3,3);
    model.damping.rayleigh_alpha = damping_alpha;
    model.damping.rayleigh_beta = damping_beta;

    state = ancf_initialize(model);
    model = state.model;
    [fixed,free,~] = ancf_constraints(model);
    [~,K] = ancf_internal_force_tangent(state.q,model);
    M = state.model.mass_matrix;
    Kff = 0.5*(K(free,free)+K(free,free).');
    Mff = 0.5*(M(free,free)+M(free,free).');
    [Vraw,Lam] = eig(Kff,Mff);
    lam_raw = real(diag(Lam));
    keep = isfinite(lam_raw) & lam_raw > 0;
    lam = lam_raw(keep);
    V = real(Vraw(:,keep));
    [lam,ord] = sort(lam,'ascend');
    V = V(:,ord);
    for j = 1:size(V,2)
        norm_m = sqrt(real(V(:,j)'*Mff*V(:,j)));
        if ~isfinite(norm_m) || norm_m <= 0
            error('export_ancf_modal_state_v3_2:Normalization', 'Invalid modal mass norm.');
        end
        V(:,j) = V(:,j)/norm_m;
    end
    nm = min(12,numel(lam));
    if nm < 12
        error('export_ancf_modal_state_v3_2:Modes', 'Fewer than twelve finite positive modes for nElem=%d.',ne);
    end
    lam = lam(1:nm);
    V = V(:,1:nm);
    qmode = zeros(model.geometry.ndof,nm);
    qmode(free,:) = V;

    node_s = linspace(0,L,model.geometry.n_node).';
    q_node_position = zeros(model.geometry.n_node,3);
    q_node_slope = zeros(model.geometry.n_node,3);
    for j = 1:model.geometry.n_node
        idx = 6*(j-1)+(1:6);
        q_node_position(j,:) = state.q(idx(1:3)).';
        q_node_slope(j,:) = state.q(idx(4:6)).';
    end
    mode_direction_xy = zeros(1,nm);
    sample_s = linspace(0,L,201).';
    mode_shape_samples = zeros(numel(sample_s),nm);
    for j = 1:nm
        [sx,sy] = sample_mode_v32(qmode(:,j),model,sample_s);
        if norm(sy) >= norm(sx)
            mode_shape_samples(:,j) = sy;
            mode_direction_xy(j) = 2;
        else
            mode_shape_samples(:,j) = sx;
            mode_direction_xy(j) = 1;
        end
        scale = max(abs(mode_shape_samples(:,j)));
        if scale > 0
            mode_shape_samples(:,j) = mode_shape_samples(:,j)/scale;
        end
    end

    mass_orthogonality = V'*Mff*V-eye(nm);
    eig_residual = zeros(1,nm);
    for j = 1:nm
        eig_residual(j) = norm(Kff*V(:,j)-lam(j)*Mff*V(:,j),2) / ...
            max([norm(Kff*V(:,j),2), abs(lam(j))*norm(Mff*V(:,j),2), eps]);
    end
    result = struct();
    result.nElem = ne;
    result.nNode = model.geometry.n_node;
    result.ndof = model.geometry.ndof;
    result.node_s_reference_m = node_s;
    result.q_static = state.q;
    result.node_position_static_m = q_node_position;
    result.node_slope_static = q_node_slope;
    result.free_dof_1based = free;
    result.fixed_dof_1based = fixed;
    result.qmode = qmode;
    result.V_free_mass_normalized = V;
    result.eigenvalues_rad2ps2 = lam;
    result.dry_frequency_Hz = sqrt(lam)/(2*pi);
    result.mode_direction_xy = mode_direction_xy;
    result.mode_shape_samples_s_m = sample_s;
    result.mode_shape_samples = mode_shape_samples;
    result.mass_orthogonality_error_fro = norm(mass_orthogonality,'fro');
    result.mass_orthogonality_error_max = max(abs(mass_orthogonality(:)));
    result.eigen_residual_by_mode = eig_residual;
    result.eigen_residual_max = max(eig_residual);
    result.static_converged = state.static.converged;
    result.static_newton_iterations = state.static.iterations;
    result.static_residual = state.static.residual;
    result.mass_matrix = M;
    result.stiffness_matrix = K;

    mat_path = fullfile(output_dir,sprintf('ancf_modal_state_nElem%d.mat',ne));
    nElem = ne; nNode = model.geometry.n_node; ndof = model.geometry.ndof;
    node_s_reference_m = node_s; q_static = state.q;
    node_position_static_m = q_node_position; node_slope_static = q_node_slope;
    free_dof_1based = free; fixed_dof_1based = fixed;
    V_free_mass_normalized = V; eigenvalues_rad2ps2 = lam;
    dry_frequency_Hz = sqrt(lam)/(2*pi); mode_direction_xy = mode_direction_xy;
    mode_shape_samples_s_m = sample_s; mode_shape_samples = mode_shape_samples;
    mass_matrix = M; stiffness_matrix = K;
    save(mat_path,'nElem','nNode','ndof','node_s_reference_m','q_static', ...
        'node_position_static_m','node_slope_static','free_dof_1based', ...
        'fixed_dof_1based','qmode','V_free_mass_normalized', ...
        'eigenvalues_rad2ps2','dry_frequency_Hz','mode_direction_xy', ...
        'mode_shape_samples_s_m','mode_shape_samples','mass_matrix', ...
        'stiffness_matrix','-v7');
    result.mat_path = mat_path;
    audit.cases{ic} = result;
end

json_path = fullfile(output_dir,'ancf_modal_state_export_audit_matlab.json');
fid = fopen(json_path,'w');
if fid < 0, error('export_ancf_modal_state_v3_2:Write', 'Cannot write audit JSON.'); end
fwrite(fid,jsonencode(audit),'char'); fclose(fid);
end

function [sx,sy] = sample_mode_v32(qmode,model,sref)
ne = model.geometry.n_elem; Le = model.geometry.L/ne;
sx = zeros(numel(sref),1); sy = zeros(numel(sref),1);
for k = 1:numel(sref)
    s = min(max(sref(k),0),model.geometry.L);
    if s == model.geometry.L, ie = ne; x = Le;
    else, ie = min(floor(s/Le)+1,ne); x = s-(ie-1)*Le; end
    S = ancf_shape(x,Le,0);
    N = [S(1)*eye(3),S(2)*eye(3),S(3)*eye(3),S(4)*eye(3)];
    idx = 6*(ie-1)+1:6*(ie-1)+12;
    r = N*qmode(idx);
    sx(k) = r(1); sy(k) = r(2);
end
end
