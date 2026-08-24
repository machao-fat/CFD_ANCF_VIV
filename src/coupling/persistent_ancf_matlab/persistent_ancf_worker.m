function persistent_ancf_worker(request_dir, ancf_root, runner_root)
%PERSISTENT_ANCF_WORKER One MATLAB process for the complete ANCF campaign.
%
% Requests and responses are one-file JSON messages.  The worker owns the
% committed/prediction/correction states and calls the checked-in ANCF core
% functions directly; it does not implement a second structural solver.

if nargin < 1 || isempty(request_dir), error('persistent_ancf_worker:Path','request_dir is required'); end
if nargin < 2 || isempty(ancf_root), error('persistent_ancf_worker:Path','ancf_root is required'); end
if nargin >= 3 && ~isempty(runner_root), addpath(runner_root); end
addpath(genpath(ancf_root));

request_dir = char(request_dir);
request_root = fullfile(request_dir, 'requests');
response_root = fullfile(request_dir, 'responses');
if ~exist(request_root,'dir'), mkdir(request_root); end
if ~exist(response_root,'dir'), mkdir(response_root); end

model = [];
committed_state = [];
prediction_state = [];
correction_state = [];
initialized = false;
global_step = -1;
pending_step = -1;
pending_time = NaN;
pending_token = '';
pending_checkpoint = '';
seen_commands = {};
worker_pid = persistent_ancf_worker_pid();

while true
    files = dir(fullfile(request_root, 'request_*.json'));
    if isempty(files)
        pause(0.01);
        continue;
    end
    [~, order] = sort({files.name});
    request_file = fullfile(request_root, files(order(1)).name);
    command_id = '';
    operation_id = 'unknown';
    should_shutdown = false;
    try
        request = jsondecode(fileread(request_file));
        delete(request_file);
        command_id = char(get_required(request, 'command_id'));
        operation_id = char(get_required(request, 'operation_id'));
        if any(strcmp(seen_commands, command_id))
            response = error_response('duplicate_command_id', 'command_id was already processed');
        else
            seen_commands{end+1} = command_id; %#ok<AGROW>
            [response, should_shutdown] = dispatch(request);
        end
    catch ME
        response = error_response(ME.identifier, ME.message);
        % Preserve the request identity on an action-level error.  The
        % Python client must be able to distinguish a valid error response
        % from an old response file.
    end
    response.command_id = command_id;
    response.operation_id = operation_id;
    response.worker_pid = worker_pid;
    response.protocol = 'stage4d-persistent-ancf-1';
    try
        write_json(fullfile(response_root, ['response_', command_id, '.json']), response);
    catch ME
        % There is no safe recovery if a response cannot be published.
        warning('persistent_ancf_worker:Response','%s',ME.message);
    end
    if should_shutdown, break; end
end

    function [response, shutdown] = dispatch(request)
        action = lower(char(get_required(request, 'action')));
        shutdown = false;
        switch action
            case 'initialize'
                if initialized, error('persistent_ancf_worker:State','worker is already initialized'); end
                config = get_required(request, 'config');
                model = build_model(config);
                committed_state = ancf_initialize(model);
                committed_state.t = get_optional_number(config, 'start_time_s', 0.0);
                committed_state.step = 0;
                prediction_state = [];
                correction_state = [];
                pending_step = -1;
                pending_time = NaN;
                pending_token = '';
                pending_checkpoint = '';
                global_step = -1;
                initialized = true;
                response = state_response('initialize', committed_state, global_step, -1, NaN);

            case 'predict'
                require_initialized();
                require_no_staged();
                [step, time_s, load] = request_step_time_load(request);
                require_step_time(step, time_s);
                prediction_state = ancf_advance_step(committed_state, load, model.time.dt);
                assert_finite_state(prediction_state);
                pending_step = step;
                pending_time = time_s;
                response = state_response('predict', prediction_state, global_step, step, time_s);

            case 'correct'
                require_initialized();
                if isempty(prediction_state) || pending_step < 0
                    error('persistent_ancf_worker:Prediction','correct requires a matching prediction');
                end
                [step, time_s, load] = request_step_time_load(request);
                if step ~= pending_step || abs(time_s-pending_time) > 1e-12*max(1,abs(time_s))
                    error('persistent_ancf_worker:Transaction','correct step/time does not match prediction');
                end
                % Always advance from committed_state.  The predictor is an
                % audit/staging state and is never used as a correction base.
                correction_state = ancf_advance_step(committed_state, load, model.time.dt);
                assert_finite_state(correction_state);
                pending_token = sprintf('ancf-%s-%d-%0.17g', char(get_optional_text(request,'operation_id','op')), step, time_s);
                response = state_response('correct', correction_state, global_step, step, time_s);
                response.checkpoint_token = pending_token;

            case 'get_state'
                require_initialized();
                view = lower(get_optional_text(request, 'view', 'committed'));
                if strcmp(view,'prediction')
                    state = prediction_state;
                elseif strcmp(view,'correction')
                    state = correction_state;
                else
                    state = committed_state;
                end
                if isempty(state), error('persistent_ancf_worker:State','requested state is not staged'); end
                response = state_response('get_state', state, global_step, pending_step, pending_time);

            case 'prepare_checkpoint'
                require_initialized();
                if isempty(correction_state) || isempty(pending_token)
                    error('persistent_ancf_worker:Checkpoint','prepare_checkpoint requires correction');
                end
                path = char(get_required(request, 'path'));
                save_checkpoint(path, correction_state, pending_step);
                pending_checkpoint = path;
                response = state_response('prepare_checkpoint', correction_state, global_step, pending_step, pending_time);
                response.checkpoint_token = pending_token;
                response.checkpoint_path = path;

            case 'save_checkpoint'
                require_initialized();
                path = char(get_required(request, 'path'));
                if ~isempty(correction_state) && ~isempty(pending_token)
                    save_checkpoint(path, correction_state, pending_step);
                    pending_checkpoint = path;
                    state = correction_state;
                    staged_step = pending_step;
                    staged_time = pending_time;
                    token = pending_token;
                else
                    save_checkpoint(path, committed_state, global_step);
                    state = committed_state;
                    staged_step = -1;
                    staged_time = NaN;
                    token = '';
                end
                response = state_response('save_checkpoint', state, global_step, staged_step, staged_time);
                response.checkpoint_path = path;
                if ~isempty(token), response.checkpoint_token = token; end

            case 'finalize_commit'
                require_initialized();
                token = get_optional_text(request, 'checkpoint_token', '');
                if isempty(correction_state) || isempty(pending_token) || ~strcmp(token, pending_token)
                    error('persistent_ancf_worker:Checkpoint','finalize_commit token mismatch or no staged correction');
                end
                if isempty(pending_checkpoint) || ~exist(pending_checkpoint,'file')
                    error('persistent_ancf_worker:Checkpoint','finalize_commit requires a prepared checkpoint file');
                end
                committed_state = correction_state;
                global_step = pending_step;
                prediction_state = [];
                correction_state = [];
                pending_step = -1;
                pending_time = NaN;
                pending_token = '';
                pending_checkpoint = '';
                response = state_response('finalize_commit', committed_state, global_step, -1, NaN);

            case 'discard_staged'
                require_initialized();
                prediction_state = [];
                correction_state = [];
                pending_step = -1;
                pending_time = NaN;
                pending_token = '';
                pending_checkpoint = '';
                response = state_response('discard_staged', committed_state, global_step, -1, NaN);

            case 'load_checkpoint'
                path = char(get_required(request, 'path'));
                loaded = load_checkpoint(path);
                committed_state = loaded.state;
                model = committed_state.model;
                global_step = loaded.global_step;
                prediction_state = [];
                correction_state = [];
                pending_step = -1;
                pending_time = NaN;
                pending_token = '';
                pending_checkpoint = '';
                initialized = true;
                response = state_response('load_checkpoint', committed_state, global_step, -1, NaN);

            case 'heartbeat'
                if initialized
                    response = state_response('heartbeat', committed_state, global_step, pending_step, pending_time);
                else
                    response = struct('status','complete','action','heartbeat','initialized',false,'step',-1,'time_s',NaN);
                end

            case 'shutdown'
                response = struct('status','complete','action','shutdown','initialized',initialized, ...
                    'step',global_step,'time_s',get_time(committed_state));
                shutdown = true;

            otherwise
                error('persistent_ancf_worker:Action','unknown action %s', action);
        end
    end

    function model_out = build_model(config)
        L = get_optional_number(config,'L',10.0);
        D = get_optional_number(config,'D',1.0);
        dInner = get_optional_number(config,'dInner',0.9);
        nElem = round(get_optional_number(config,'nElem',2));
        nSlices = round(get_optional_number(config,'nSlices',3));
        topTension = get_optional_number(config,'topTension_N',1.0e7);
        E = get_optional_number(config,'youngs_modulus_Pa',2.07e11);
        dt = get_optional_number(config,'dt',0.0025);
        model_out = vertical_ttr_case('L',L,'D',D,'dInner',dInner,'nElem',nElem, ...
            'nSlices',nSlices,'topTension_N',topTension,'youngs_modulus_Pa',E,'dt',dt);
        if isfield(config,'s_ref_m'), model_out.coupling.s_ref_m = double(config.s_ref_m(:)); end
        % Keep the physical flags and default model definition identical to
        % the Stage 4C-B BatchMatlabANCFRunner.  The worker is a transport
        % change, not a physics change.
        model_out.damping.rayleigh_alpha = get_optional_number(config,'rayleigh_alpha',0.0);
        model_out.damping.rayleigh_beta = get_optional_number(config,'rayleigh_beta',0.0);
        model_out.time.newton_tolerance = get_optional_number(config,'newton_tolerance',1.0e-8);
        model_out.time.max_newton = round(get_optional_number(config,'max_newton',40));
        model_out.static.external_slice_force_N = zeros(numel(model_out.coupling.s_ref_m),3);
    end

    function [step, time_s, load] = request_step_time_load(request)
        step = round(get_optional_number(request,'step',-1));
        time_s = get_optional_number(request,'time_s',NaN);
        load = double(get_required(request,'load'));
        ns = numel(model.coupling.s_ref_m);
        if isvector(load), load = reshape(load,ns,3); end
        if ~isequal(size(load),[ns,3]), error('persistent_ancf_worker:Load','load must be ns x 3'); end
        if any(~isfinite(load(:))), error('persistent_ancf_worker:Load','load contains NaN/Inf'); end
    end

    function require_step_time(step, time_s)
        if step ~= global_step + 1, error('persistent_ancf_worker:Step','expected step %d, received %d',global_step+1,step); end
        expected = committed_state.t + model.time.dt;
        if ~isfinite(time_s) || abs(time_s-expected) > 1e-12*max(1,abs(expected))
            error('persistent_ancf_worker:Time','expected time %.17g, received %.17g',expected,time_s);
        end
    end

    function require_initialized()
        if ~initialized || isempty(committed_state), error('persistent_ancf_worker:State','worker is not initialized'); end
    end

    function require_no_staged()
        if ~isempty(prediction_state) || ~isempty(correction_state), error('persistent_ancf_worker:Transaction','staged state already exists'); end
    end

    function response = state_response(action, state, committed_step, staged_step, staged_time)
        assert_finite_state(state);
        response = struct('status','complete','action',action,'initialized',true, ...
            'step',committed_step,'time_s',state.t,'global_step',committed_step, ...
            'staged_step',staged_step,'staged_time_s',staged_time, ...
            'q',state.q(:).','qdot',state.qd(:).','qddot',state.qdd(:).', ...
            'newton_iterations',get_optional_number(state.diagnostics,'iterations',0), ...
            'newton_residual',get_optional_number(state.diagnostics,'residual',0), ...
            'converged',logical(get_optional_number(state.diagnostics,'converged',1)), ...
            'min_tension_N',min(state.output.tension_N(:)), ...
            'max_tension_N',max(state.output.tension_N(:)), ...
            'motion',motion_json(ancf_slice_motion(state)));
    end

    function value = motion_json(motion)
        ns = numel(motion.slice_id);
        value = repmat(struct('slice_id',0,'s_ref_m',0,'x_m',0,'y_m',0,'z_m',0, ...
            'vx_mps',0,'vy_mps',0,'vz_mps',0,'ax_mps2',0,'ay_mps2',0,'az_mps2',0),ns,1);
        for ii = 1:ns
            value(ii).slice_id = motion.slice_id(ii);
            value(ii).s_ref_m = motion.s_ref_m(ii);
            value(ii).x_m = motion.x_m(ii); value(ii).y_m = motion.y_m(ii); value(ii).z_m = motion.z_m(ii);
            value(ii).vx_mps = motion.vx_mps(ii); value(ii).vy_mps = motion.vy_mps(ii); value(ii).vz_mps = motion.vz_mps(ii);
            value(ii).ax_mps2 = motion.ax_mps2(ii); value(ii).ay_mps2 = motion.ay_mps2(ii); value(ii).az_mps2 = motion.az_mps2(ii);
        end
    end

    function save_checkpoint(path, state, checkpoint_global_step)
        assert_finite_state(state);
        [folder,~,~] = fileparts(path);
        if isempty(folder), folder = pwd; end
        if ~exist(folder,'dir'), mkdir(folder); end
        checkpoint = struct('schema_version','stage4d-persistent-ancf-checkpoint-1', ...
            'state',state,'global_step',checkpoint_global_step,'time_s',state.t, ...
            'q',state.q,'qdot',state.qd,'qddot',state.qdd, ...
            'last_slice_force_N',state.last_slice_force_N);
        tmp = [tempname(folder),'.mat'];
        save(tmp,'checkpoint','-v7');
        movefile(tmp,path,'f');
    end

    function loaded = load_checkpoint(path)
        if ~exist(path,'file'), error('persistent_ancf_worker:Checkpoint','checkpoint not found'); end
        S = load(path);
        if isfield(S,'checkpoint')
            loaded.state = S.checkpoint.state;
            loaded.global_step = round(S.checkpoint.global_step);
        elseif isfield(S,'state')
            loaded.state = S.state;
            loaded.global_step = round(loaded.state.step)-1;
        else
            error('persistent_ancf_worker:Checkpoint','checkpoint has no state');
        end
        required = {'q','qd','qdd','t','step','last_slice_force_N','model'};
        for ii = 1:numel(required)
            if ~isfield(loaded.state,required{ii}), error('persistent_ancf_worker:Checkpoint','checkpoint missing %s',required{ii}); end
        end
        assert_finite_state(loaded.state);
    end

    function assert_finite_state(state)
        if any(~isfinite(state.q(:))) || any(~isfinite(state.qd(:))) || any(~isfinite(state.qdd(:))) || ...
                ~isfinite(state.t) || any(~isfinite(state.last_slice_force_N(:)))
            error('persistent_ancf_worker:Finite','state contains NaN/Inf');
        end
        if isfield(state,'output') && (any(~isfinite(state.output.tension_N(:))) || ...
                ~isfinite(state.output.mechanical_energy_J))
            error('persistent_ancf_worker:Finite','state output contains NaN/Inf');
        end
    end

    function value = get_required(s, name)
        if ~isstruct(s) || ~isfield(s,name), error('persistent_ancf_worker:Schema','missing field %s',name); end
        value = s.(name);
    end

    function value = get_optional_number(s, name, default)
        if isstruct(s) && isfield(s,name) && ~isempty(s.(name)), value = double(s.(name)); else, value = default; end
        if ~(isscalar(value) && (isfinite(value) || isnan(value))), error('persistent_ancf_worker:Schema','invalid numeric field %s',name); end
    end

    function value = get_optional_text(s, name, default)
        if isstruct(s) && isfield(s,name) && ~isempty(s.(name)), value = char(s.(name)); else, value = default; end
    end

    function value = get_time(state)
        if isempty(state), value = NaN; else, value = state.t; end
    end

    function response = error_response(code, message)
        response = struct('status','error','error_code',char(code),'message',char(message));
    end

    function write_json(path, value)
        text = jsonencode(value);
        folder = fileparts(path);
        tmp = [tempname(folder),'.json'];
        fid = fopen(tmp,'w','n','UTF-8');
        if fid < 0, error('persistent_ancf_worker:Response','cannot open response'); end
        fwrite(fid,text,'char'); fwrite(fid,newline,'char'); fclose(fid);
        movefile(tmp,path,'f');
    end

    function value = request_if_defined()
        value = struct();
    end

    function value = persistent_ancf_worker_pid()
        try, value = feature('getpid'); catch, value = 0; end
    end
end
