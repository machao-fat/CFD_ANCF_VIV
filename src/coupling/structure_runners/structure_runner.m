classdef structure_runner < handle
    %STRUCTURE_RUNNER Persistent ANCF/EB state with predictor rollback.
    % The predictor advances a temporary copy only.  The corrector advances
    % the persistent state exactly once with the newly validated load.

    properties
        branch
        config
        model
        state
        pending_prediction
        initialized = false
    end

    methods
        function obj = structure_runner(branch, config)
            if nargin < 1, branch = 'eb'; end
            if nargin < 2, config = struct(); end
            obj.branch = lower(char(branch));
            obj.config = config;
        end

        function initialize(obj, config)
            if nargin >= 2 && ~isempty(config), obj.config = config; end
            c = obj.config;
            L = structure_runner.get(c,'L',1.0);
            D = structure_runner.get(c,'D',0.028);
            dInner = structure_runner.get(c,'dInner',0.024);
            nElem = structure_runner.get(c,'nElem',2);
            nSlices = structure_runner.get(c,'nSlices',1);
            topTension = structure_runner.get(c,'topTension_N',1.0e5);
            youngsModulus = structure_runner.get(c,'youngs_modulus_Pa',2.07e11);
            dt = structure_runner.get(c,'dt',0.0025);
            if strcmp(obj.branch,'eb')
                obj.model = eb_ttr_case('L',L,'D',D,'dInner',dInner, ...
                    'nElem',nElem,'nSlices',nSlices,'topTension_N',topTension, ...
                    'youngs_modulus_Pa',youngsModulus, ...
                    'dt',dt,'rayleigh_alpha',structure_runner.get(c,'rayleigh_alpha',0), ...
                    'rayleigh_beta',structure_runner.get(c,'rayleigh_beta',0));
                obj.model.physics.include_gravity = false;
                obj.model.physics.include_buoyancy = false;
                % The online comparator deliberately removes body forces.
                % eb_ttr_case computes the ANCF-matched pre-tension gradient
                % before these flags are changed, so clear that cached unit
                % weight as well.  Otherwise EB retains a tension gradient
                % while the ANCF runner carries the uniform applied top
                % tension, an error that becomes material for large L/D.
                obj.model.pretension.ancf_initial_weight_Npm = 0.0;
                obj.model.static.distributed_load_Npm = [0;0];
                obj.model.static.external_slice_force_N = zeros(nSlices,3);
                if isfield(c,'s_ref_m'), obj.model.coupling.s_ref_m = c.s_ref_m(:); end
                obj.state = eb_initialize(obj.model);
            elseif strcmp(obj.branch,'ancf')
                obj.model = vertical_ttr_case('L',L,'D',D,'dInner',dInner, ...
                    'nElem',nElem,'nSlices',nSlices,'topTension_N',topTension, ...
                    'youngs_modulus_Pa',youngsModulus, ...
                    'dt',dt);
                obj.model.physics.include_gravity = false;
                obj.model.physics.include_buoyancy = false;
                obj.model.damping.rayleigh_alpha = structure_runner.get(c,'rayleigh_alpha',0);
                obj.model.damping.rayleigh_beta = structure_runner.get(c,'rayleigh_beta',0);
                obj.model.time.newton_tolerance = structure_runner.get(c,'newton_tolerance',1.0e-8);
                obj.model.time.max_newton = structure_runner.get(c,'max_newton',40);
                obj.model.static.external_slice_force_N = zeros(nSlices,3);
                if isfield(c,'s_ref_m'), obj.model.coupling.s_ref_m = c.s_ref_m(:); end
                obj.state = ancf_initialize(obj.model);
            else
                error('structure_runner:Branch','Unknown branch %s.',obj.branch);
            end
            obj.pending_prediction = [];
            obj.initialized = true;
        end

        function [motion,audit] = predict(obj, step, time_s, previous_load)
            obj.require_initialized();
            obj.require_load(previous_load);
            if step ~= obj.state.step + 1
                error('structure_runner:Step','Predict step %d does not follow state step %d.',step,obj.state.step);
            end
            dt = obj.config_value('dt',obj.model.time.dt);
            if abs(time_s-(obj.state.t+dt)) > 1.0e-10*max(1,abs(time_s))
                error('structure_runner:Time','Predict time %.16g does not follow state time %.16g.',time_s,obj.state.t+dt);
            end
            base = obj.state;
            if strcmp(obj.branch,'eb')
                trial = eb_advance_step(base,previous_load,dt);
                motion = eb_slice_motion(trial);
                audit = structure_runner.audit(trial.output,trial.diagnostics);
            else
                trial = ancf_advance_step(base,previous_load,dt);
                motion = ancf_slice_motion(trial);
                audit = structure_runner.audit(trial.output,trial.diagnostics);
            end
            motion.step = step; motion.time_s = time_s;
            obj.pending_prediction = struct('step',step,'time_s',time_s,'state',base,'motion',motion,'audit',audit);
        end

        function [motion,audit] = correct(obj, step, time_s, current_load)
            obj.require_initialized();
            obj.require_load(current_load);
            if isempty(obj.pending_prediction) || obj.pending_prediction.step ~= step
                error('structure_runner:Prediction','Correct called without matching prediction.');
            end
            dt = obj.config_value('dt',obj.model.time.dt);
            if strcmp(obj.branch,'eb')
                obj.state = eb_advance_step(obj.state,current_load,dt);
                motion = eb_slice_motion(obj.state);
                audit = structure_runner.audit(obj.state.output,obj.state.diagnostics);
            else
                obj.state = ancf_advance_step(obj.state,current_load,dt);
                motion = ancf_slice_motion(obj.state);
                audit = structure_runner.audit(obj.state.output,obj.state.diagnostics);
            end
            if abs(obj.state.t-time_s) > 1.0e-10*max(1,abs(time_s))
                error('structure_runner:Time','Corrected state time %.16g differs from %.16g.',obj.state.t,time_s);
            end
            motion.step = step; motion.time_s = time_s;
            audit.corrected = true;
            obj.pending_prediction = [];
        end

        function motion = get_motion(obj)
            obj.require_initialized();
            if strcmp(obj.branch,'eb'), motion = eb_slice_motion(obj.state);
            else, motion = ancf_slice_motion(obj.state); end
        end

        function energy = get_energy(obj)
            obj.require_initialized();
            out = obj.state.output;
            energy = struct('kinetic_energy_J',out.kinetic_energy_J, ...
                'mechanical_energy_J',out.mechanical_energy_J);
            energy.stored_energy_J = out.mechanical_energy_J;
            energy.external_potential_energy_J = out.external_potential_J;
            if strcmp(obj.branch,'eb')
                energy.bending_energy_J = out.bending_energy_J;
                energy.axial_strain_energy_J = out.axial_strain_energy_J;
                energy.pre_tension_geometric_energy_J = out.pre_tension_geometric_energy_J;
                energy.internal_energy_J = out.bending_energy_J + out.axial_strain_energy_J;
                energy.min_tension_N = out.min_tension_N;
                energy.max_tension_N = out.max_tension_N;
                energy.reference_tension_N = out.min_tension_N;
                energy.min_dynamic_tension_increment_N = 0;
                energy.max_dynamic_tension_increment_N = 0;
                energy.tension_location_index = find(out.tension_profile_N == out.min_tension_N,1,'first');
                energy.compression_risk = logical(out.compression_risk);
                energy.tension_definition_code = 1;
                energy.max_slope = max(abs([out.slope_x(:);out.slope_y(:)]));
            else
                energy.bending_energy_J = 0;
                energy.axial_strain_energy_J = out.internal_energy_J;
                energy.pre_tension_geometric_energy_J = 0;
                energy.internal_energy_J = out.internal_energy_J;
                reference_tension = obj.model.boundary.top_tension_N;
                dynamic_increment = out.tension_N-reference_tension;
                [energy.min_tension_N,imin] = min(out.tension_N);
                energy.max_tension_N = max(out.tension_N);
                energy.reference_tension_N = reference_tension;
                energy.min_dynamic_tension_increment_N = min(dynamic_increment);
                energy.max_dynamic_tension_increment_N = max(dynamic_increment);
                energy.tension_location_index = imin;
                energy.compression_risk = logical(energy.min_tension_N < -1.0e-10*max(1,reference_tension));
                energy.tension_definition_code = 2;
                energy.max_slope = max(sqrt(sum((out.tangent(:,1:2)).^2,2)));
            end
            energy.max_curvature_1pm = max(out.curvature_mag_1pm);
            if strcmp(obj.branch,'eb')
                Qmapped = eb_external_load(obj.state,obj.state.last_slice_force_N);
                damping_power = obj.state.qd.'*obj.state.model.matrices.C*obj.state.qd;
            else
                Qmapped = ancf_external_load(obj.state,obj.state.last_slice_force_N);
                damping_power = obj.state.qd.'*obj.state.model.damping_matrix*obj.state.qd;
            end
            energy.mapped_generalized_force_norm_N = norm(Qmapped,inf);
            energy.damping_power_W = damping_power;
            energy.step = obj.state.step;
            energy.time_s = obj.state.t;
        end

        function save_checkpoint(obj, filepath)
            obj.require_initialized();
            [folder,~,~] = fileparts(filepath);
            if isempty(folder), folder = pwd; end
            if ~exist(folder,'dir'), mkdir(folder); end
            runner_state = obj.state; %#ok<NASGU>
            branch = obj.branch; %#ok<NASGU>
            config = obj.config; %#ok<NASGU>
            pending_prediction = obj.pending_prediction; %#ok<NASGU>
            tmp = [tempname(folder),'.mat'];
            cleanup = onCleanup(@() structure_runner.delete_if_exists(tmp));
            save(tmp,'runner_state','branch','config','pending_prediction','-v7');
            movefile(tmp,filepath,'f');
            clear cleanup
        end

        function load_checkpoint(obj, filepath)
            loaded = load(filepath,'runner_state','branch','config','pending_prediction');
            obj.state = loaded.runner_state;
            obj.branch = loaded.branch;
            obj.config = loaded.config;
            obj.model = obj.state.model;
            if isfield(loaded,'pending_prediction'), obj.pending_prediction = loaded.pending_prediction;
            else, obj.pending_prediction = []; end
            obj.initialized = true;
        end

        function finalize(obj)
            obj.pending_prediction = [];
            obj.initialized = false;
        end
    end

    methods (Access=private)
        function require_initialized(obj)
            if ~obj.initialized, error('structure_runner:State','Runner is not initialized.'); end
        end
        function require_load(obj, load)
            ns = numel(obj.model.coupling.s_ref_m);
            if ~isnumeric(load) || ~isequal(size(load),[ns,3]) || any(~isfinite(load(:)))
                error('structure_runner:Load','Expected finite %d x 3 integrated-N load.',ns);
            end
        end
        function value = config_value(obj,name,default)
            value = structure_runner.get(obj.config,name,default);
        end
    end

    methods (Static, Access=private)
        function value = get(s,name,default)
            if isstruct(s) && isfield(s,name) && ~isempty(s.(name)), value = s.(name); else, value = default; end
        end
        function out = audit(output,diagnostics)
            out = struct('iterations',diagnostics.iterations, ...
                'initial_residual',structure_runner.field(diagnostics,'initial_residual',diagnostics.residual), ...
                'residual',diagnostics.residual, ...
                'residual_scale',structure_runner.field(diagnostics,'residual_scale',1), ...
                'initial_relative_residual',structure_runner.field(diagnostics,'initial_relative_residual',NaN), ...
                'relative_residual',structure_runner.field(diagnostics,'relative_residual',NaN), ...
                'tolerance_relative',structure_runner.field(diagnostics,'tolerance_relative',NaN), ...
                'converged',diagnostics.converged,'mechanical_energy_J',output.mechanical_energy_J);
        end
        function value = field(s,name,default)
            if isstruct(s) && isfield(s,name) && ~isempty(s.(name)), value = s.(name); else, value = default; end
        end
        function delete_if_exists(filepath)
            if exist(filepath,'file'), delete(filepath); end
        end
    end
end
