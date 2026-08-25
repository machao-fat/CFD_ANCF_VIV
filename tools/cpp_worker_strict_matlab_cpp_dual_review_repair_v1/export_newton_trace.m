function export_newton_trace(source_mat, output_json)
loaded=load(char(source_mat),'state'); if ~isfield(loaded,'state'),error('stage186:Source');end
state=loaded.state; root=fileparts(fileparts(fileparts(mfilename('fullpath')))); addpath(genpath(fullfile(root,'src','structure_ancf_matlab')));
model=state.model; dt=model.time.dt; beta=model.time.beta; gamma=model.time.gamma; force=state.last_slice_force_N;
[fixed,free,values]=ancf_constraints(model); Qext=state.base_load+ancf_external_load(state,force); M=model.mass_matrix; C=model.damping_matrix;
q_n=state.q; qd_n=state.qd; qdd_n=state.qdd; q_pred=q_n+dt*qd_n+dt^2*(0.5-beta)*qdd_n; qd_pred=qd_n+dt*(1-gamma)*qdd_n; q=q_pred; q(fixed)=values(fixed);
items=cell(model.time.max_newton,1); scale=max(1.0,norm(Qext(free),inf)); count=0;
for iter=1:model.time.max_newton
 qdd=(q-q_pred)/(beta*dt^2); qd=qd_pred+gamma*dt*qdd; [qi,K]=ancf_internal_force_tangent(q,model); R=M*qdd+C*qd+qi-Qext; R(fixed)=0; rn=norm(R(free),inf); count=count+1;
 item=struct('iteration',iter,'q',q.','qdot',qd.','qddot',qdd.','internal_force',qi.','residual',R.','residual_norm',rn,'converged',false,'increment',zeros(1,numel(q)),'tangent',K);
 if rn<=model.time.newton_tolerance*scale, item.converged=true; items{count}=item; break; end
 Keff=M/(beta*dt^2)+C*gamma/(beta*dt)+K; dq=-Keff(free,free)\R(free); q(free)=q(free)+dq; q(fixed)=values(fixed); item.increment(free)=dq.'; items{count}=item;
end
items=items(1:count); out=struct('schema_version',1,'source_step',double(state.step),'source_time_s',double(state.t),'target_step',560,'target_time_s',double(state.t+dt),'global_dt',double(dt),'residual_scale',scale,'iterations',{items});
encoded=jsonencode(out); fid=fopen(char(output_json),'w','n','UTF-8'); if fid<0,error('stage186:Output');end; fwrite(fid,[encoded newline],'char'); fclose(fid);
end
