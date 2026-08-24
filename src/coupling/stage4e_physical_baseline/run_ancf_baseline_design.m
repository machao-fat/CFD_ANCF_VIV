function report = run_ancf_baseline_design(output_json)
%RUN_ANCF_BASELINE_DESIGN Offline Stage 4E-A structural audit.
% This wrapper only calls the existing read-only ANCF production functions.
% It performs static equilibrium, dry modal analysis, mesh convergence and
% an added-mass sensitivity estimate. It does not start OpenFOAM or modify
% any production solver code.

if nargin < 1 || isempty(output_json)
    error('run_ancf_baseline_design:Output', 'An output JSON path is required.');
end

this_file = mfilename('fullpath');
this_dir = fileparts(this_file);
project_root = fileparts(fileparts(fileparts(this_dir)));
ancf_dir = fullfile(project_root, 'src', 'structure_ancf_matlab');
addpath(ancf_dir);

configs = { ...
    struct('id','public_vivdatashare_bidirectional', ...
        'source_kind','public_experiment_and_code', ...
        'L',7.64,'D',0.02841,'dInner',0.025, ...
        'mass_per_length',1.24,'EI',58.6,'EA',9.4e5, ...
        'top_tension',980.0,'fluid_rho',1000.0, ...
        'U_ref',0.48,'zeta_percent',2.58, ...
        'gravity',false,'buoyancy',false,'nSlices',3), ...
    struct('id','frozen_project_vertical_ttr', ...
        'source_kind','project_frozen_parameters', ...
        'L',10.0,'D',1.0,'dInner',0.9, ...
        'mass_per_length',1171.421360699,'EI',3.4943984173e9, ...
        'EA',3.0889709766e10,'top_tension',1.0e7, ...
        'fluid_rho',1025.0,'U_ref',1.0,'zeta_percent',0.0, ...
        'gravity',true,'buoyancy',true,'nSlices',3) ...
    };
n_elem_values = [2,4,8,16];

report = struct();
report.schema_version = '0.1.0';
report.analysis = 'offline ANCF static equilibrium and dry modal audit';
report.openfoam_started = false;
report.read_only_core = true;
report.n_elem_values = n_elem_values;
report.configurations = cell(numel(configs),1);

for ic = 1:numel(configs)
    c = configs{ic};
    cfg = struct();
    cfg.id = c.id;
    cfg.source_kind = c.source_kind;
    cfg.parameters = c;
    cfg.mass_ratio_no_added_mass = c.mass_per_length / ...
        (c.fluid_rho*pi*c.D^2/4.0);
    cfg.results = cell(numel(n_elem_values),1);

    for ie = 1:numel(n_elem_values)
        ne = n_elem_values(ie);
        model = vertical_ttr_case('L',c.L,'D',c.D,'dInner',c.dInner, ...
            'nElem',ne,'nSlices',c.nSlices,'topTension_N',c.top_tension, ...
            'youngs_modulus_Pa',2.07e11,'dt',1.0e-3);
        model.material.rho = c.mass_per_length / model.material.area;
        model.material.EA = c.EA;
        model.material.EI = c.EI;
        model.fluid.rho = c.fluid_rho;
        model.physics.include_gravity = c.gravity;
        model.physics.include_buoyancy = c.buoyancy;
        model.static.external_slice_force_N = zeros(c.nSlices,3);
        model.damping.rayleigh_alpha = 0.0;
        model.damping.rayleigh_beta = 0.0;

        state = ancf_initialize(model);
        model = state.model;
        [fixed,free,~] = ancf_constraints(model);
        [~,K] = ancf_internal_force_tangent(state.q,model);
        M = state.model.mass_matrix;
        Kff = 0.5*(K(free,free)+K(free,free).');
        Mff = 0.5*(M(free,free)+M(free,free).');
        [V,Lam] = eig(Kff,Mff);
        lam = real(diag(Lam));
        keep = isfinite(lam) & lam > 0;
        lam = lam(keep);
        V = real(V(:,keep));
        [lam,ord] = sort(lam,'ascend');
        V = V(:,ord);
        freq = sqrt(lam)/(2*pi);
        nm = min(12,numel(freq));
        freq = freq(1:nm);
        V = V(:,1:nm);

        qmode = zeros(model.geometry.ndof,nm);
        qmode(free,:) = V;
        sample_s = linspace(0,c.L,201).';
        shape_samples = zeros(numel(sample_s),nm);
        shape_direction = zeros(nm,1);
        for im = 1:nm
            [sx,sy] = sample_mode(qmode(:,im),model,sample_s);
            if norm(sy) >= norm(sx)
                shape_samples(:,im) = sy;
                shape_direction(im) = 2;
            else
                shape_samples(:,im) = sx;
                shape_direction(im) = 1;
            end
            scale = max(abs(shape_samples(:,im)));
            if scale > 0
                shape_samples(:,im) = shape_samples(:,im)/scale;
            end
        end

        straight_z = sample_s;
        static_x = state.output.x_m;
        static_y = state.output.y_m;
        static_z = state.output.z_m - model.post.s_ref_m(:);
        result = struct();
        result.nElem = ne;
        result.nNode = model.geometry.n_node;
        result.ndof = model.geometry.ndof;
        result.free_dof_count = numel(free);
        result.fixed_dof_count = numel(fixed);
        result.static_converged = state.static.converged;
        result.static_load_steps = state.static.load_steps;
        result.static_newton_iterations = state.static.iterations;
        result.static_residual = state.static.residual;
        result.static_max_abs_displacement_m = max([max(abs(static_x)),max(abs(static_y)),max(abs(static_z))]);
        result.static_max_abs_x_m = max(abs(static_x));
        result.static_max_abs_y_m = max(abs(static_y));
        result.static_max_abs_z_change_m = max(abs(static_z));
        result.static_tension_min_N = min(state.output.tension_N);
        result.static_tension_max_N = max(state.output.tension_N);
        result.static_mechanical_energy_J = state.output.mechanical_energy_J;
        result.dry_frequency_Hz = freq(:).';
        result.dry_mode_direction_xy = shape_direction(:).';
        result.modal_shape_samples_s_m = sample_s(:).';
        result.modal_shape_samples = shape_samples;
        result.straight_z_reference_m = straight_z(:).';
        result.model_mass_per_length_kgpm = c.mass_per_length;
        result.model_area_m2 = model.material.area;
        result.model_EA_N = model.material.EA;
        result.model_EI_Nm2 = model.material.EI;
        cfg.results{ie} = result;
    end

    cfg.mesh_convergence = mesh_convergence(cfg.results);
    cfg.wet_frequency_sensitivity = wet_frequency_sensitivity(cfg, c);
    report.configurations{ic} = cfg;
end

report.generated_by = mfilename('fullpath');
report.generated_utc = datestr(now,'yyyy-mm-ddTHH:MM:SSZ');
payload = jsonencode(report);
fid = fopen(output_json,'w');
if fid < 0
    error('run_ancf_baseline_design:Write', 'Cannot open output JSON: %s',output_json);
end
fwrite(fid,payload,'char');
fclose(fid);
end

function [sx,sy] = sample_mode(qmode,model,sref)
ne = model.geometry.n_elem;
Le = model.geometry.L/ne;
sx = zeros(numel(sref),1);
sy = zeros(numel(sref),1);
for k = 1:numel(sref)
    s = min(max(sref(k),0),model.geometry.L);
    if s == model.geometry.L
        ie = ne; x = Le;
    else
        ie = min(floor(s/Le)+1,ne); x = s-(ie-1)*Le;
    end
    S = ancf_shape(x,Le,0);
    N = [S(1)*eye(3),S(2)*eye(3),S(3)*eye(3),S(4)*eye(3)];
    idx = 6*(ie-1)+1:6*(ie-1)+12;
    r = N*qmode(idx);
    sx(k) = r(1);
    sy(k) = r(2);
end
end

function out = mesh_convergence(results)
out = struct();
out.adjacent_pairs = cell(max(0,numel(results)-1),1);
for k = 1:numel(results)-1
    a = results{k}; b = results{k+1};
    n = min(numel(a.dry_frequency_Hz),numel(b.dry_frequency_Hz));
    rel = abs(b.dry_frequency_Hz(1:n)-a.dry_frequency_Hz(1:n))./max(abs(b.dry_frequency_Hz(1:n)),eps);
    mac = zeros(1,n);
    mac_matrix = zeros(n,n);
    for j = 1:n
        va = a.modal_shape_samples(:,j);
        for l = 1:n
            vb = b.modal_shape_samples(:,l);
            mac_matrix(j,l) = abs(va'*vb)^2/max((va'*va)*(vb'*vb),eps);
        end
        mac(j) = mac_matrix(j,j);
    end
    major_n = min(3,n);
    mac_major_best = max(mac_matrix(1:major_n,1:major_n),[],2).';
    p = struct('coarse_nElem',a.nElem,'fine_nElem',b.nElem, ...
        'frequency_relative_error',rel,'frequency_max_relative_error',max(rel), ...
        'frequency_first_mode_relative_error',rel(1), ...
        'mac_same_index',mac,'mac_same_index_min',min(mac), ...
        'mac_major_best',mac_major_best,'mac_major_min',min(mac_major_best), ...
        'frequency_pass_1pct',max(rel)<=0.01, ...
        'major_modes_pass_2pct',max(rel(1:min(3,n)))<=0.02, ...
        'mac_pass_0p99',min(mac_major_best)>=0.99);
    out.adjacent_pairs{k} = p;
end
if ~isempty(out.adjacent_pairs)
    out.formal_4_vs_8 = out.adjacent_pairs{2};
    out.formal_4_vs_8_note = 'Modal shapes are compared on a common 201-point span grid; nElem=2 is a coarse diagnostic only.';
end
end

function out = wet_frequency_sensitivity(cfg,c)
% Added-mass estimate only. No CFD or experimental wet frequency is inferred.
Ca_values = [0.5,1.0,1.5];
base = cfg.results{end}.dry_frequency_Hz;
m_disp = c.fluid_rho*pi*c.D^2/4.0;
out = struct();
out.status = 'approximate_added_mass_only';
out.added_mass_coefficient_candidates = Ca_values;
out.displaced_mass_per_length_kgpm = m_disp;
out.source_experimental_wet_frequency = 'not_available_in_audited_public_source';
out.candidates = zeros(numel(Ca_values),numel(base));
for k = 1:numel(Ca_values)
    out.candidates(k,:) = base*sqrt(c.mass_per_length/(c.mass_per_length+Ca_values(k)*m_disp));
end
out.nElem_for_estimate = cfg.results{end}.nElem;
out.warning = 'Do not mix these estimates with dry ANCF frequencies or an unverified experimental wet frequency.';
end
