function ancf_diagnostic_replay(input_path, output_path)
%ANCF_DIAGNOSTIC_REPLAY Offline ANCF-only force replay for Stage 4D-C-A-v2.
% This function calls the checked-in ANCF core, never OpenFOAM or the
% persistent worker.  It evaluates release and static-preload routes using
% the same developed-flow force history and four diagnostic time steps.

spec = jsondecode(fileread(input_path));
times = double(spec.force.times_s(:));
forces = double(spec.force.values_N);
if size(forces,1) ~= numel(times) && size(forces,2) == numel(times)
    forces = forces.';
end
if size(forces,1) ~= numel(times) || size(forces,2) ~= 9
    error('ancf_diagnostic_replay:ForceShape','Force history must be N x 9 in slice-major [Fx,Fy,Fz] rows.');
end
F0 = double(spec.force.initial_force_N);
if ~isequal(size(F0),[3,3])
    error('ancf_diagnostic_replay:InitialForceShape','Initial force must be 3 x 3.');
end

dts = double(spec.dt_values_s(:).');
duration = double(spec.duration_s);
routes = {'release','preload'};
out = struct();
out.schema_version = 'stage4d-c-a-v2-ancf-replay-1';
out.duration_s = duration;
out.dt_values_s = dts;
out.force_time_count = numel(times);
out.force_initial_N = F0;
out.routes = struct();

for iroute = 1:numel(routes)
    route = routes{iroute};
    route_out = struct();
    for idt = 1:numel(dts)
        dt = dts(idt);
        model = vertical_ttr_case('L',10.0,'D',1.0,'dInner',0.9, ...
            'nElem',2,'nSlices',3,'topTension_N',1.0e7, ...
            'youngs_modulus_Pa',2.07e11,'dt',dt);
        if strcmp(route,'preload')
            model.static.external_slice_force_N = F0;
            load_mode = 'incremental_force_F_minus_F0';
        else
            model.static.external_slice_force_N = zeros(3,3);
            load_mode = 'full_force_F';
        end
        state0 = ancf_initialize(model);
        [fixed,free,~] = ancf_constraints(model);
        [~,K] = ancf_internal_force_tangent(state0.q,model);
        M = state0.model.mass_matrix;
        Mff = 0.5*(M(free,free)+M(free,free).');
        Kff = 0.5*(K(free,free)+K(free,free).');
        [V,D] = eig(Kff,Mff);
        lambda = real(diag(D));
        keep = isfinite(lambda) & lambda > 1.0e-8;
        lambda = lambda(keep); V = real(V(:,keep));
        [lambda,order] = sort(lambda,'ascend'); V = V(:,order);
        nmode = min(3,numel(lambda));
        phi = zeros(model.geometry.ndof,nmode);
        for imode = 1:nmode
            v = V(:,imode);
            v = v / sqrt(max(v.'*Mff*v,eps));
            phi(free,imode) = v;
        end

        nstep = round(duration/dt);
        tvec = (1:nstep).'*dt;
        qhist = zeros(nstep,model.geometry.ndof);
        qdhist = qhist; qddhist = qhist;
        motion_pos = zeros(nstep,9);
        motion_vel = zeros(nstep,9);
        motion_acc = zeros(nstep,9);
        force_hist = zeros(nstep,9);
        iterations = zeros(nstep,1); residual = zeros(nstep,1);
        min_tension = zeros(nstep,1); max_tension = zeros(nstep,1);
        work_structure = zeros(nstep,1);
        state = state0;
        for istep = 1:nstep
            ttarget = tvec(istep);
            frow = interp1(times,forces,ttarget,'linear','extrap');
            f = reshape(frow,3,3).';
            if strcmp(route,'preload')
                f = f - F0;
            end
            state = ancf_advance_step(state,f,dt);
            qhist(istep,:) = state.q(:).';
            qdhist(istep,:) = state.qd(:).';
            qddhist(istep,:) = state.qdd(:).';
            motion = ancf_slice_motion(state);
            motion_pos(istep,:) = reshape([motion.x_m,motion.y_m,motion.z_m].',1,9);
            motion_vel(istep,:) = reshape([motion.vx_mps,motion.vy_mps,motion.vz_mps].',1,9);
            motion_acc(istep,:) = reshape([motion.ax_mps2,motion.ay_mps2,motion.az_mps2].',1,9);
            force_hist(istep,:) = reshape(f.',1,9);
            iterations(istep) = state.diagnostics.iterations;
            residual(istep) = state.diagnostics.residual;
            min_tension(istep) = min(state.output.tension_N(:));
            max_tension(istep) = max(state.output.tension_N(:));
            vel_center = reshape(motion_vel(istep,:),3,3).';
            work_structure(istep) = sum(sum(f .* vel_center)) * dt;
        end

        run = struct();
        run.route = route;
        run.load_mode = load_mode;
        run.dt_s = dt;
        run.steps = nstep;
        run.time_s = tvec;
        run.q = qhist;
        run.qdot = qdhist;
        run.qddot = qddhist;
        run.motion_position = motion_pos;
        run.motion_velocity = motion_vel;
        run.motion_acceleration = motion_acc;
        run.force_integrated_N = force_hist;
        run.newton_iterations = iterations;
        run.newton_residual = residual;
        run.min_tension_N = min_tension;
        run.max_tension_N = max_tension;
        run.W_structure_J = work_structure;
        run.q_static = state0.q(:).';
        run.qdot_initial = state0.qd(:).';
        run.qddot_initial = state0.qdd(:).';
        run.static_diagnostics = state0.static;
        run.static_motion_position = reshape([ancf_slice_motion(state0).x_m, ...
            ancf_slice_motion(state0).y_m, ancf_slice_motion(state0).z_m].',1,9);
        run.fixed_indices_1based = fixed(:).';
        run.free_indices_1based = free(:).';
        run.mass_matrix = M;
        run.modal_phi = phi;
        run.modal_frequency_Hz = sqrt(lambda(1:nmode))/(2*pi);
        field = dt_field(dt);
        route_out.(field) = run;
    end
    out.routes.(route) = route_out;
end

text = jsonencode(out);
folder = fileparts(output_path);
if ~exist(folder,'dir'), mkdir(folder); end
tmp = [tempname(folder),'.json'];
fid = fopen(tmp,'w','n','UTF-8');
if fid < 0, error('ancf_diagnostic_replay:Output','Cannot open output.'); end
fwrite(fid,text,'char'); fwrite(fid,newline,'char'); fclose(fid);
movefile(tmp,output_path,'f');
end

function field = dt_field(dt)
field = strrep(sprintf('dt_%0.7g',dt),'.','_');
field = strrep(field,'-','m');
end
