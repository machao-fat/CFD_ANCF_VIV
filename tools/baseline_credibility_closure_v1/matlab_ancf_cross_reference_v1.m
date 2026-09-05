function result = matlab_ancf_cross_reference_v1(output_json)
%MATLAB_ANCF_CROSS_REFERENCE_V1 Independent MATLAB side of the V1 baseline.
% This uses the protected MATLAB ANCF implementation unchanged.  The input
% contract is frozen in this file and mirrors the C++ diagnostic exactly.
if nargin ~= 1, error('baselineCross:Arguments','expected output_json'); end
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(root,'src','structure_ancf_matlab')));

contract = struct('L_m',50.0,'D_m',1.0,'Di_m',0.9,'elements',16, ...
    'slices',3,'slice_positions_m',[8.333333333333334;25.0;41.666666666666664], ...
    'E_Pa',3227125779.2218256,'material_density_kgpm3',26315.789473684214, ...
    'fluid_density_kgpm3',1000.0,'gravity_mps2',9.81, ...
    'top_tension_N',2179104.0029808935,'dt_s',0.005,'duration_s',50.0, ...
    'beta',0.25,'gamma',0.5,'newton_tolerance',1.0e-8,'max_newton',40, ...
    'internal_gauss_order',3,'mass_gauss_order',5,'static_load_steps',40, ...
    'static_relaxation',0.8,'damping_alpha',0.0,'damping_beta',0.0, ...
    'perturbation_m',1.0e-4,'output_every_steps',5);

model = vertical_ttr_case('L',contract.L_m,'D',contract.D_m,'dInner',contract.Di_m, ...
    'nElem',contract.elements,'nSlices',contract.slices,'topTension_N',contract.top_tension_N, ...
    'youngs_modulus_Pa',contract.E_Pa,'dt',contract.dt_s);
model.material.rho = contract.material_density_kgpm3;
model.fluid.rho = contract.fluid_density_kgpm3;
model.fluid.g = contract.gravity_mps2;
model.integration.n_gauss = contract.internal_gauss_order;
model.time.beta = contract.beta; model.time.gamma = contract.gamma;
model.time.newton_tolerance = contract.newton_tolerance; model.time.max_newton = contract.max_newton;
model.damping.rayleigh_alpha = contract.damping_alpha; model.damping.rayleigh_beta = contract.damping_beta;
model.static.n_load_steps = contract.static_load_steps; model.static.max_newton = contract.max_newton;
model.static.tolerance = contract.newton_tolerance; model.coupling.s_ref_m = contract.slice_positions_m;
state = ancf_initialize(model);
static_state = state;
[static_internal,static_tangent] = ancf_internal_force_tangent(static_state.q,static_state.model);

static_samples = repmat(struct('s_m',0,'x_m',0,'y_m',0,'z_m',0),2*contract.elements+1,1);
for i = 0:2*contract.elements
    s = 0.5*contract.L_m*i/contract.elements;
    r = evaluate_position(static_state,s);
    static_samples(i+1) = struct('s_m',s,'x_m',r(1),'y_m',r(2),'z_m',r(3));
end

modal = matlab_modes(static_state,6);
for k = 1:6
    modal.modes(k).normalized_nodal_y_shape = nodal_shape(static_state,modal.full_modes(:,k));
end

% Shared, analytic first-mode-like displacement: y=A sin(pi*s/L), with the
% exact corresponding nodal y-slope. It is intentionally independent of
% either solver's eigenvectors, so q0/qdot0/qddot are identical by contract.
for node = 0:contract.elements
    s = contract.L_m*node/contract.elements; base = 6*node;
    state.q(base+2) = state.q(base+2) + contract.perturbation_m*sin(pi*s/contract.L_m);
    state.q(base+5) = state.q(base+5) + contract.perturbation_m*pi/contract.L_m*cos(pi*s/contract.L_m);
end
state.qd(:) = 0.0; state.qdd(:) = 0.0;
equilibrium_energy = static_state.output.mechanical_energy_J;
steps = round(contract.duration_s/contract.dt_s);
if abs(steps*contract.dt_s-contract.duration_s) > 1e-12, error('baselineCross:Time','duration/dt mismatch'); end
count = floor(steps/contract.output_every_steps)+1;
samples = repmat(struct('time_s',0,'kinetic_J',0,'strain_energy_J',0,'incremental_energy_J',0, ...
    'y_0',0,'vy_0',0,'y_1',0,'vy_1',0,'y_2',0,'vy_2',0),count,1);
write_index = 1; zero_load = zeros(contract.slices,3);
for step = 0:steps
    if mod(step,contract.output_every_steps) == 0 || step == steps
        motion = ancf_slice_motion(state); post = state.output;
        samples(write_index) = struct('time_s',state.t,'kinetic_J',post.kinetic_energy_J, ...
            'strain_energy_J',post.internal_energy_J,'incremental_energy_J',post.mechanical_energy_J-equilibrium_energy, ...
            'y_0',motion.y_m(1),'vy_0',motion.vy_mps(1),'y_1',motion.y_m(2),'vy_1',motion.vy_mps(2), ...
            'y_2',motion.y_m(3),'vy_2',motion.vy_mps(3));
        write_index = write_index + 1;
    end
    if step ~= steps, state = ancf_advance_step(state,zero_load,contract.dt_s); end
end
if write_index ~= count+1, error('baselineCross:Sampling','sample-count mismatch'); end

result = struct('schema_version','baseline_credibility_closure_v1.matlab_reference.1', ...
    'engine',struct('name','MATLAB','version',version), ...
    'contract',contract,'static',struct('diagnostics',static_state.static,'samples',static_samples), ...
    'core',struct('mass_matrix',static_state.model.mass_matrix,'internal_force',static_internal(:).','tangent_matrix',static_tangent), ...
    'modal',modal,'dynamic',struct('initial_condition','analytic_y_equals_A_sin_pi_s_over_L', ...
        'qdot_zero',true,'qddot_zero',true,'zero_fluid_force',true,'samples',samples));
tmp = [char(output_json) '.tmp'];
fid = fopen(tmp,'w','n','UTF-8'); if fid < 0, error('baselineCross:Output','cannot open output'); end
fwrite(fid,[jsonencode(result) newline],'char'); fclose(fid);
if ~movefile(tmp,char(output_json),'f'), error('baselineCross:Output','atomic rename failed'); end
end

function r = evaluate_position(state,s)
model = state.model; Le = model.geometry.L/model.geometry.n_elem;
if s == model.geometry.L, ie = model.geometry.n_elem; x = Le; else, ie = min(floor(s/Le)+1,model.geometry.n_elem); x = s-(ie-1)*Le; end
S = ancf_shape(x,Le,0); N = [S(1)*eye(3),S(2)*eye(3),S(3)*eye(3),S(4)*eye(3)];
q = state.q(6*(ie-1)+1:6*(ie-1)+12); r = N*q;
end

function modal = matlab_modes(state,nmode)
model = state.model; [~,Kfull] = ancf_internal_force_tangent(state.q,model);
nnode = model.geometry.n_node; y_dof = reshape([6*(0:nnode-1)+2;6*(0:nnode-1)+5],[],1);
fixed = [2,6*(nnode-1)+2]; free = setdiff(y_dof,fixed,'stable');
K = 0.5*(Kfull(free,free)+Kfull(free,free).'); M = 0.5*(model.mass_matrix(free,free)+model.mass_matrix(free,free).');
[V,D] = eig(K,M,'vector'); keep = isfinite(D) & real(D)>1e-12 & abs(imag(D))<1e-9;
D = real(D(keep)); V = real(V(:,keep)); [D,order] = sort(D); V = V(:,order);
if numel(D)<nmode, error('baselineCross:Modes','fewer than six positive modes'); end
D = D(1:nmode); V = V(:,1:nmode); full_modes = zeros(model.geometry.ndof,nmode);
modes = repmat(struct('index',0,'frequency_hz',0,'mass_norm',0,'residual',0,'normalized_nodal_y_shape',[]),nmode,1);
for k = 1:nmode
    V(:,k) = V(:,k)/sqrt(V(:,k).'*M*V(:,k)); full_modes(free,k) = V(:,k);
    residual = norm(K*V(:,k)-D(k)*M*V(:,k))/(norm(K*V(:,k))+abs(D(k))*norm(M*V(:,k))+eps);
    modes(k) = struct('index',k,'frequency_hz',sqrt(D(k))/(2*pi),'mass_norm',V(:,k).'*M*V(:,k),'residual',residual,'normalized_nodal_y_shape',[]);
end
modal = struct('modes',modes,'free_dof_matlab_1based',free(:).','full_modes',full_modes);
end

function value = nodal_shape(state,mode)
nnode = state.model.geometry.n_node; value = zeros(1,nnode);
for node = 0:nnode-1, value(node+1) = mode(6*node+2); end
scale = max(abs(value)); if scale <= 0, error('baselineCross:Mode','zero modal shape'); end
value = value/scale;
end
