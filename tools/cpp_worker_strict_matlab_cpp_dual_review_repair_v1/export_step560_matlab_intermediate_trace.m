function export_step560_matlab_intermediate_trace(output_json)
%EXPORT_STEP560_MATLAB_INTERMEDIATE_TRACE Stage186 bounded MATLAB export.
% This script is the only MATLAB entry point for Stage186. It searches the
% read-only committed checkpoints for one exact step-559 numerical contract,
% then emits a JSON trace with the same staged quantities as the C++ forensic
% diagnostic. No checkpoint is modified and no CFD process is started.
if nargin ~= 1 || ~(ischar(output_json) || isstring(output_json))
    error('stage186:Arguments', 'output_json is required');
end
output_json = char(output_json);
project_root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(project_root, 'src', 'structure_ancf_matlab')));

% Locate an exact immutable source. The accepted step-559 seed is stored in
% the protected persistent-worker runtime rather than results/**. It was the
% source recorded by the earlier authorized MATLAB golden export. Include it
% explicitly, then retain the committed-checkpoint scan for future stages.
seed_candidate = fullfile(project_root, 'runtime', 'cpp_worker_persistent_ipc_v1', ...
    'matlab_dual_011', 'accepted_step559_seed.mat');
files = dir(fullfile(project_root, 'results', '**', 'committed.mat'));
candidates = {};
if isfile(seed_candidate)
    candidates{end+1} = seed_candidate; %#ok<AGROW>
end
for k = 1:numel(files)
    candidates{end+1} = fullfile(files(k).folder, files(k).name); %#ok<AGROW>
end
matches = {};
for k = 1:numel(candidates)
    candidate = candidates{k};
    try
        loaded = load(candidate, 'state');
        if ~isfield(loaded, 'state'), continue; end
        s = loaded.state;
        if ~isfield(s, 'model') || double(s.step) ~= 559 || abs(double(s.t)-2.2075) > 1e-12
            continue;
        end
        m = s.model;
        if double(m.integration.n_gauss) ~= 5 || double(m.time.max_newton) ~= 50 || ...
                abs(double(m.time.dt)-0.00125) > 1e-15
            continue;
        end
        matches{end+1} = candidate; %#ok<AGROW>
    catch
        % A malformed/unsupported old artifact is not a valid source match.
    end
end
if numel(matches) ~= 1
    error('stage186:SourceAmbiguous', 'expected exactly one matching source, found %d', numel(matches));
end
source_mat = matches{1};
loaded = load(source_mat, 'state');
state = loaded.state;
model = state.model;
dt = double(model.time.dt);
source_step = double(state.step);
source_time = double(state.t);
source_tick = round(source_time * 1e9);
if source_step ~= 559 || abs(source_time - 2.2075) > 1e-12 || source_tick ~= 2207500000
    error('stage186:SourceIdentity', 'source identity mismatch');
end
if ~isfield(state, 'last_slice_force_N')
    error('stage186:ForceMissing', 'source slice force is missing');
end
slice_force = state.last_slice_force_N;
if size(slice_force, 1) ~= numel(model.coupling.s_ref_m) || size(slice_force, 2) ~= 3
    error('stage186:ForceSchema', 'slice force dimensions mismatch');
end

% Capture the source state and execute exactly one target advance. The trace
% function below duplicates the public MATLAB formula without changing it.
q_n = state.q(:); qd_n = state.qd(:); qdd_n = state.qdd(:);
q_pred = q_n + dt*qd_n + dt^2*(0.5-model.time.beta)*qdd_n;
Qext = state.base_load + ancf_external_load(state, slice_force);
[target_trace, internal_source, tangent_source] = trace_internal(state.q, model, 560, 1); %#ok<ASGLU>
state_after = ancf_advance_step(state, slice_force, dt);
[target_trace_after, internal_target, tangent_target] = trace_internal(state_after.q, model, 560, 2); %#ok<ASGLU>
target_time = double(state_after.t);
target_tick = round(target_time*1e9);
if double(state_after.step) ~= 560 || abs(target_time-2.20875) > 1e-12 || target_tick ~= 2208750000
    error('stage186:TargetIdentity', 'target identity mismatch');
end

trace = struct();
trace.schema_version = 1;
trace.trace_layout = 'float64 JSON arrays; vectors column-major; element ascending; Gauss ascending';
trace.stage_id = 'stage4f_d_cpp_worker_strict_matlab_cpp_dual_review_repair_v1';
trace.run_id = 'cpp_worker_strict_matlab_cpp_dual_review_001';
trace.case_id = 'cpp_worker_strict_matlab_cpp_dual_review_case_001';
trace.source_mat = source_mat;
trace.source_global_step = source_step;
trace.source_time_s = source_time;
trace.source_integer_tick = source_tick;
trace.target_global_step = 560;
trace.target_case_local_bridge_step = 1;
trace.target_time_s = target_time;
trace.target_integer_tick = target_tick;
trace.global_dt = dt;
trace.request_id = 1860005601;
trace.transaction_id = 1860005601;
trace.q_source = q_n.';
trace.qdot_source = qd_n.';
trace.qddot_source = qdd_n.';
trace.predictor = q_pred.';
trace.corrector = state_after.q(:).';
trace.external_force = Qext(:).';
trace.generalized_force = Qext(:).';
trace.q_target = state_after.q(:).';
trace.qdot_target = state_after.qd(:).';
trace.qddot_target = state_after.qdd(:).';
trace.internal_force_source = internal_source(:).';
trace.internal_force_target = internal_target(:).';
trace.newton_residual = double(state_after.diagnostics.residual);
trace.newton_iterations = double(state_after.diagnostics.iterations);
trace.finite_value_audit = all(isfinite([q_n;qd_n;qdd_n;state_after.q(:);state_after.qd(:);state_after.qdd(:);Qext(:);internal_source(:);internal_target(:)]));
trace.points_source = target_trace.points;
trace.points_target = target_trace_after.points;
trace.element_force_source = target_trace.element_force;
trace.element_force_target = target_trace_after.element_force;
trace.element_tangent_source = target_trace.element_tangent;
trace.element_tangent_target = target_trace_after.element_tangent;
trace.internal_force_accumulated_source = target_trace.force;
trace.internal_force_accumulated_target = target_trace_after.force;
trace.internal_force_tangent_source = target_trace.tangent;
trace.internal_force_tangent_target = target_trace_after.tangent;
trace.output_hash = sha256_hex(typecast(double([trace.q_target, trace.qdot_target, trace.qddot_target, ...
    trace.internal_force_target, trace.external_force, trace.generalized_force, trace.predictor, trace.corrector]), 'uint8'));
trace.output_size_bytes = numel(typecast(double([trace.q_target, trace.qdot_target, trace.qddot_target, ...
    trace.internal_force_target, trace.external_force, trace.generalized_force, trace.predictor, trace.corrector]), 'uint8'));
trace.output_mtime_ns = file_mtime_ns(output_json);
encoded = jsonencode(trace);
tmp = [output_json '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('stage186:Output', 'cannot open output'); end
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, [encoded newline], 'char');
clear cleanup;
if ~movefile(tmp, output_json, 'f')
    error('stage186:OutputRename', 'atomic output rename failed');
end
% Re-open after the atomic rename to record authoritative size/mtime/hash.
bytes = read_bytes(output_json);
meta = struct('schema_version',1,'stage_id',trace.stage_id,'run_id',trace.run_id, ...
    'case_id',trace.case_id,'source_mat',source_mat,'trace_sha256',sha256_hex(bytes), ...
    'size_bytes',numel(bytes),'mtime_ns',file_mtime_ns(output_json),'finite_value_audit',trace.finite_value_audit, ...
    'source_count',numel(matches));
fid = fopen([output_json '.manifest.json'], 'w', 'n', 'UTF-8');
if fid < 0, error('stage186:Manifest', 'cannot open manifest'); end
fwrite(fid, [jsonencode(meta) newline], 'char'); fclose(fid);
end

function [result, force, tangent] = trace_internal(q, model, step, phase)
ne = model.geometry.n_elem; Le = model.geometry.L/ne; EA = model.material.EA; EI = model.material.EI;
[xi,w] = ancf_gauss_points(model.integration.n_gauss); n = model.geometry.ndof;
result = struct('points',{{}},'element_force',zeros(ne,12),'element_tangent',{{}},'force',zeros(n,1),'tangent',zeros(n,n));
result.points = cell(ne*numel(xi),1); result.element_tangent = cell(ne,1);
force = zeros(n,1); tangent = zeros(n,n); point_index = 0;
for ie=1:ne
    qe=q(6*(ie-1)+(1:12)); fe=zeros(12,1); Ke=zeros(12,12);
    for k=1:numel(xi)
        point_index=point_index+1; x=0.5*(xi(k)+1)*Le; S1=ancf_shape(x,Le,1); S2=ancf_shape(x,Le,2);
        I3=eye(3); B=[S1(1)*I3,S1(2)*I3,S1(3)*I3,S1(4)*I3]; C=[S2(1)*I3,S2(2)*I3,S2(3)*I3,S2(4)*I3];
        a=B*qe; b=C*qe; a2=dot(a,a); v=cross(a,b); v2=dot(v,v); eps=0.5*(a2-1);
        if a2<1e-24,error('stage186:Degenerate','degenerate ANCF tangent');end
        Xa=cross_matrix(a); Xb=cross_matrix(b); Xv=cross_matrix(v); I3=eye(3);
        ga_b=a2^(-3)*(Xb*v)-3*v2*a2^(-4)*a; gb_b=-a2^(-3)*(Xa*v);
        Haa_b=-a2^(-3)*(Xb*Xb)-6*a2^(-4)*(Xb*v)*a.'-3*a2^(-4)*a*(Xb*v).'+24*v2*a2^(-5)*(a*a.')-3*v2*a2^(-4)*I3;
        Hab_b=a2^(-3)*(-Xv+Xb*Xa)+3*a2^(-4)*a*(Xa*v).'; Hbb_b=-a2^(-3)*(Xa*Xa);
        ga=EA*eps*a+EI*ga_b; gb=EI*gb_b; Haa=EA*(a*a.'+eps*I3)+EI*Haa_b; Hab=EI*Hab_b; Hbb=EI*Hbb_b;
        bga=B.'*ga; cgb=C.'*gb; contribution=(bga+cgb)*w(k)*Le/2;
        tangent_contribution=(B.'*Haa*B+B.'*Hab*C+C.'*Hab.'*B+C.'*Hbb*C)*w(k)*Le/2;
        fe=fe+contribution; Ke=Ke+tangent_contribution;
        p=struct('element_id',ie-1,'gauss_index',k-1,'xi',xi(k),'x',x,'weight',w(k), ...
            'a',a.','b',b.','a_squared',a2,'v',v.','v_squared',v2,'eps',eps,'ga_b',ga_b.','gb_b',gb_b.', ...
            'ga',ga.','gb',gb.','B_t_ga',bga.','C_t_gb',cgb.','internal_force_contribution',contribution.', ...
            'tangent_contribution',tangent_contribution.','phase',phase);
        result.points{point_index}=p;
    end
    result.element_force(ie,:)=fe.'; result.element_tangent{ie}=Ke; force(6*(ie-1)+(1:12))=force(6*(ie-1)+(1:12))+fe; tangent(6*(ie-1)+(1:12),6*(ie-1)+(1:12))=tangent(6*(ie-1)+(1:12),6*(ie-1)+(1:12))+Ke;
end
tangent=0.5*(tangent+tangent.'); result.force=force; result.tangent=tangent;
end

function X=cross_matrix(a)
X=[0,-a(3),a(2);a(3),0,-a(1);-a(2),a(1),0];
end
function bytes=read_bytes(path)
fid=fopen(path,'r','n'); if fid<0,error('stage186:Read','cannot read output');end
bytes=fread(fid,Inf,'*uint8'); fclose(fid);
end
function ns=file_mtime_ns(path)
d=dir(path); if isempty(d), ns=0; else, ns=round(posixtime(datetime(d.datenum,'ConvertFrom','datenum'))*1e9); end
end
function hex=sha256_hex(bytes), md=java.security.MessageDigest.getInstance('SHA-256'); md.update(int8(bytes(:))); j=md.digest(); u=zeros(1,numel(j),'uint8'); for k=1:numel(j), v=double(j(k)); if v<0,v=v+256;end,u(k)=uint8(v);end, hex=lower(reshape(dec2hex(u,2).',1,[])); end
