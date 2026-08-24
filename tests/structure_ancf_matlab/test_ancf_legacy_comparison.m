function report = test_ancf_legacy_comparison()
%TEST_ANCF_LEGACY_COMPARISON Compare old and new element force/tangent.
this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src = fullfile(project_root,'src','structure_ancf_matlab');
legacy = 'D:\研二文件\开题准备\ANCF\Run4v4_wuzfv2\Run4v4_wuzfv2\Run4v4_wu';
if ~exist(legacy,'dir')
    error('test_ancf_legacy_comparison:Missing', 'Legacy package not found: %s',legacy);
end

restoredefaultpath;
addpath(fullfile(legacy,'ANCF_Modelling'),fullfile(legacy,'Sym'));
ne = 12;
Riser = struct('Nne',ne,'Nnode',ne+1,'Ndof',6*(ne+1));
RiserEle = struct('Le',ones(ne,1),'EA',ones(ne,1)*1e5,'EI',ones(ne,1)*1e2);
q = zeros(Riser.Ndof,1);
for inode = 0:ne
    base = 6*inode+1;
    s = inode;
    q(base) = s;
    q(base+1) = 0.02*sin(s/2);
    q(base+2) = 0.01*cos(s/3);
    q(base+3) = 1;
    q(base+4) = 0.01*cos(s/2)/2;
    q(base+5) = -0.01*sin(s/3)/3;
end
[Qold,Kold] = elastic_forces_stiffness(q,1,Riser,RiserEle);
rmpath(fullfile(legacy,'ANCF_Modelling'),fullfile(legacy,'Sym'));
addpath(src);
model = vertical_ttr_case('L',12,'D',0.02,'dInner',0.015,'nElem',ne, ...
    'nSlices',5,'topTension_N',0);
model.material.EA = 1e5;
model.material.EI = 1e2;
model.integration.n_gauss = 5;
[Qnew,Knew] = ancf_internal_force_tangent(q,model);

force_relative_error = norm(Qold-Qnew)/max(1,norm(Qold));
tangent_relative_error = norm(Kold-Knew,'fro')/max(1,norm(Kold,'fro'));
assert(force_relative_error < 1e-3, 'Legacy force comparison exceeded tolerance.');
assert(tangent_relative_error < 1e-3, 'Legacy tangent comparison exceeded tolerance.');

report = struct('passed',true,'force_relative_error',force_relative_error, ...
    'tangent_relative_error',tangent_relative_error,'nElem',ne,'gauss_order',5);
fprintf('PASS legacy comparison: Qrel=%.3e Krel=%.3e\n', ...
    force_relative_error,tangent_relative_error);
end
