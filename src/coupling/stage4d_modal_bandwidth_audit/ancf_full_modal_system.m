function ancf_full_modal_system(input_path, output_path)
%ANCF_FULL_MODAL_SYSTEM Build the complete nElem=2 linearized modal system.
% This helper is deliberately offline and calls only the checked-in ANCF core.

spec = jsondecode(fileread(input_path));
model = vertical_ttr_case('L',10.0,'D',1.0,'dInner',0.9, ...
    'nElem',2,'nSlices',3,'topTension_N',1.0e7, ...
    'youngs_modulus_Pa',2.07e11,'dt',double(spec.dt_s));
model.static.external_slice_force_N = zeros(3,3);
state = ancf_initialize(model);
[fixed,free,values] = ancf_constraints(model);
[~,Kraw] = ancf_internal_force_tangent(state.q,model);
M = state.model.mass_matrix;
M = 0.5*(M+M.');
K = 0.5*(Kraw+Kraw.');
Mff = M(free,free);
Kff = K(free,free);
[V,D] = eig(Kff,Mff);
lambda = real(diag(D));
if any(~isfinite(lambda)) || any(lambda <= 0)
    error('ancf_full_modal_system:Eigenvalues','All free eigenvalues must be finite and positive.');
end
[lambda,order] = sort(lambda,'ascend');
V = real(V(:,order));
for imode = 1:numel(lambda)
    v = V(:,imode);
    v = v / sqrt(v.'*Mff*v);
    V(:,imode) = v;
end
phi = zeros(model.geometry.ndof,numel(lambda));
phi(free,:) = V;

out = struct();
out.schema_version = 'stage4d-c-a-v3-full-modal-system-1';
out.protocol_version = '0.2.1';
out.dt_s = double(spec.dt_s);
out.nElem = model.geometry.n_elem;
out.nSlices = numel(model.coupling.s_ref_m);
out.ndof = model.geometry.ndof;
out.free_dof_count = numel(free);
out.mode_count = numel(lambda);
out.fixed_indices_1based = fixed(:).';
out.free_indices_1based = free(:).';
out.fixed_values = values(:).';
out.q_static = state.q(:).';
out.qdot_static = state.qd(:).';
out.qddot_static = state.qdd(:).';
out.mass_matrix = M;
out.tangent_stiffness = K;
out.mass_free = Mff;
out.tangent_stiffness_free = Kff;
out.mapping_H3 = state.model.mapping.H3;
out.eigenvalues = lambda(:).';
out.frequencies_Hz = sqrt(lambda(:)).'/(2*pi);
out.modal_phi_full = phi;
out.modal_phi_free = V;
out.model_identity = struct('L_m',10.0,'D_m',1.0,'dInner_m',0.9, ...
    'E_Pa',2.07e11,'topTension_N',1.0e7,'nElem',2,'nSlices',3, ...
    's_ref_m',model.coupling.s_ref_m(:).','unit_span_m',1.0, ...
    'rayleigh_alpha',model.damping.rayleigh_alpha, ...
    'rayleigh_beta',model.damping.rayleigh_beta);

text = jsonencode(out);
folder = fileparts(output_path);
if ~exist(folder,'dir'), mkdir(folder); end
tmp = [tempname(folder),'.json'];
fid = fopen(tmp,'w','n','UTF-8');
if fid < 0, error('ancf_full_modal_system:Output','Cannot open output.'); end
fwrite(fid,text,'char'); fwrite(fid,newline,'char'); fclose(fid);
movefile(tmp,output_path,'f');
end
