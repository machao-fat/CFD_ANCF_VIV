function matlab_worker_loop(runtime_root)
% Persistent user-session MATLAB worker. It never starts CFD.
runtime_root = char(runtime_root);
request_dir = fullfile(runtime_root, 'requests');
response_dir = fullfile(runtime_root, 'responses');
stop_path = fullfile(runtime_root, 'stop.request');
if ~exist(response_dir, 'dir'), mkdir(response_dir); end
% Record an independent worker environment probe before accepting requests.
% GUI/ApplicationService messages are intentionally not treated as a pass.
probe = struct('release', version('-release'), 'architecture', computer('arch'), ...
    'license', double(license('test', 'MATLAB')), 'pid', double(feature('getpid')), ...
    'TEMP', getenv('TEMP'), 'TMP', getenv('TMP'), 'TMPDIR', getenv('TMPDIR'), ...
    'PREFDIR', getenv('PREFDIR'), 'timestamp_ns', uint64(posixtime(datetime('now')) * 1e9));
write_json_atomic(fullfile(runtime_root, 'worker_environment_probe.json'), probe);
processed = strings(0, 1);
in_memory_state = false;
state = struct();
committed_state = struct();
rollback_state = struct();
while ~isfile(stop_path)
    files = dir(fullfile(request_dir, '*.json'));
    for index = 1:numel(files)
        name = string(files(index).name);
        if any(processed == name), continue; end
        request_path = fullfile(request_dir, char(name));
        try
            request = jsondecode(fileread(request_path));
            payload = request.payload;
            if strcmp(request.operation, 'initialize')
                addpath(genpath(char(payload.ancf_source)));
                if isfield(payload, 'resume_native') && ~isempty(payload.resume_native)
                    loaded = load(char(payload.resume_native), 'state');
                    if ~isfield(loaded, 'state'), error('stage94:resume', 'native resume has no state'); end
                    state = loaded.state;
                else
                    model = vertical_ttr_case('L',10,'D',1,'dInner',0.9,'nElem',2,'nSlices',3, ...
                        'topTension_N',1e7,'youngs_modulus_Pa',2.07e11,'dt',payload.dt_s);
                    if isfield(payload, 's_ref_m') && ~isempty(payload.s_ref_m)
                        model.coupling.s_ref_m = payload.s_ref_m(:);
                    end
                    state = ancf_initialize(model);
                end
                state.t = payload.start_time_s;
                committed_state = state;
                rollback_state = state;
                in_memory_state = isfield(payload, 'in_memory_state') && logical(payload.in_memory_state);
                save(char(fullfile(payload.work_dir, 'committed.mat')), 'state', '-v7');
                state_view = state_view_from_struct(state);
            elseif strcmp(request.operation, 'prediction') || strcmp(request.operation, 'correction')
                if in_memory_state
                    % The worker owns the authoritative committed state.  The
                    % legacy source/target paths remain in the request for
                    % audit compatibility but are not reloaded on prediction.
                    if strcmp(request.operation, 'correction')
                        rollback_state = committed_state;
                    end
                    state = ancf_advance_step(committed_state, payload.forces, payload.dt_s);
                    if strcmp(request.operation, 'correction')
                        committed_state = state;
                        % Persist exactly once per accepted correction so the
                        % formal checkpoint manager can hash a native artifact.
                        save(char(fullfile(payload.work_dir, 'committed.mat')), 'state', '-v7');
                    end
                else
                    loaded = load(char(payload.source_mat), 'state');
                    state = ancf_advance_step(loaded.state, payload.forces, payload.dt_s);
                    save(char(payload.target_mat), 'state', '-v7');
                end
                state_view = state_view_from_struct(state);
            elseif strcmp(request.operation, 'rollback')
                if ~in_memory_state
                    error('stage4f:rollback', 'rollback is only available in in-memory mode');
                end
                state = rollback_state;
                committed_state = rollback_state;
                save(char(fullfile(runtime_root, 'matlab_runner_rollback.mat')), 'state', '-v7');
                state_view = state_view_from_struct(state);
            else
                error('stage94:operation', 'unsupported worker operation');
            end
            response_payload = struct('state_view', state_view, 'time_s', request.time_s);
            response = make_response(request, response_payload, 0, '');
        catch exception
            response_payload = struct('state_view', struct('q', [], 'qddot', [], 'qdot', []), 'time_s', request.time_s);
            response = make_response(request, response_payload, 1, exception.message);
        end
        response_path = fullfile(response_dir, char(name));
        write_json_atomic(response_path, response);
        processed(end+1,1) = name; %#ok<AGROW>
    end
    pause(0.02);
end
end

function view = state_view_from_struct(state)
view = struct('q', state.q(:).', 'qddot', state.qdd(:).', 'qdot', state.qd(:).');
end

function response = make_response(request, payload, return_code, message)
encoded = jsonencode(payload);
response = struct('schema_version', request.schema_version, 'formal_protocol_version', request.formal_protocol_version, ...
    'operation', request.operation, 'run_id', request.run_id, 'case_id', request.case_id, ...
    'global_step', request.global_step, 'case_local_bridge_step', request.case_local_bridge_step, ...
    'time_s', request.time_s, 'integer_tick', request.integer_tick, 'request_id', request.request_id, ...
    'transaction_id', request.transaction_id, 'payload_hash', request.payload_hash, ...
    'output_sha256', sha256_text([encoded newline]), 'output_size', numel(uint8([encoded newline])), ...
    'output_mtime_ns', uint64(posixtime(datetime('now')) * 1e9), 'return_code', return_code, ...
    'finite_value_audit', struct('finite', return_code == 0), 'worker_pid', feature('getpid'), ...
    'worker_creation_time', uint64(1), 'parent_pid', uint64(1), 'command_line', strings(0,1), ...
    'payload', payload);
if ~isempty(message), response.error = message; end
end

function write_json_atomic(path, value)
temporary = [path '.tmp'];
fid = fopen(temporary, 'w', 'n', 'UTF-8');
fwrite(fid, jsonencode(value), 'char');
fclose(fid);
movefile(temporary, path, 'f');
end

function digest = sha256_text(text)
engine = java.security.MessageDigest.getInstance('SHA-256');
bytes = uint8(unicode2native(char(text), 'UTF-8'));
raw = engine.digest(bytes);
digest = lower(reshape(dec2hex(typecast(raw, 'uint8'))', 1, []));
end
