function matlab_structure_worker(request_dir, ancf_root, eb_root)
%MATLAB_STRUCTURE_WORKER Long-lived file worker for ANCF or EB.
% One MATLAB process owns one structure_runner object. Requests are JSON
% files; motion is written through the existing validated MATLAB CSV writer.

if nargin < 1, error('matlab_structure_worker:Path','request_dir is required.'); end
if nargin >= 2 && ~isempty(ancf_root), addpath(ancf_root); end
if nargin >= 3 && ~isempty(eb_root), addpath(eb_root); end
if ~exist(request_dir,'dir'), mkdir(request_dir); end
response_dir = fullfile(request_dir,'responses');
if ~exist(response_dir,'dir'), mkdir(response_dir); end
request_path = fullfile(request_dir,'request.json');
runner = [];

while true
    if ~exist(request_path,'file')
        pause(0.01);
        continue;
    end
    try
        request = jsondecode(fileread(request_path));
        delete(request_path);
        action = char(request.action);
        if strcmp(action,'shutdown')
            write_json(fullfile(response_dir,'response.json'),struct('status','complete','action','shutdown'));
            break;
        end
        if strcmp(action,'initialize')
            runner = structure_runner(char(request.branch),request.config);
            runner.initialize(request.config);
            response = make_response(runner,'initialize');
        elseif strcmp(action,'predict')
            load = normalize_load(request.load,runner);
            [motion,audit] = runner.predict(double(request.step),double(request.time_s),load);
            write_motion(motion,runner.branch,fullfile(response_dir,'motion_predict.csv'));
            response = make_response(runner,'predict');
            response.audit = audit;
            response.motion_path = fullfile(response_dir,'motion_predict.csv');
        elseif strcmp(action,'correct')
            load = normalize_load(request.load,runner);
            [motion,audit] = runner.correct(double(request.step),double(request.time_s),load);
            write_motion(motion,runner.branch,fullfile(response_dir,'motion_correct.csv'));
            response = make_response(runner,'correct');
            response.audit = audit;
            response.motion_path = fullfile(response_dir,'motion_correct.csv');
        elseif strcmp(action,'get_motion')
            motion = runner.get_motion();
            write_motion(motion,runner.branch,fullfile(response_dir,'motion_current.csv'));
            response = make_response(runner,'get_motion');
            response.motion_path = fullfile(response_dir,'motion_current.csv');
        elseif strcmp(action,'get_energy')
            response = make_response(runner,'get_energy');
        elseif strcmp(action,'save_checkpoint')
            runner.save_checkpoint(char(request.path));
            response = make_response(runner,'save_checkpoint');
        elseif strcmp(action,'load_checkpoint')
            runner.load_checkpoint(char(request.path));
            response = make_response(runner,'load_checkpoint');
        else
            error('matlab_structure_worker:Action','Unknown action %s.',action);
        end
        response.status = 'complete';
    catch ME
        response = struct('status','error','message',ME.message,'identifier',ME.identifier);
    end
    write_json(fullfile(response_dir,'response.json'),response);
end
end

function load = normalize_load(value,runner)
load = double(value);
ns = numel(runner.model.coupling.s_ref_m);
if isvector(load), load = reshape(load,ns,3); end
if ~isequal(size(load),[ns,3]), error('matlab_structure_worker:Load','Load size is not ns x 3.'); end
end

function write_motion(motion,branch,path)
if strcmp(branch,'eb'), eb_write_slice_motion_csv(motion,path);
else, ancf_write_slice_motion_csv(motion,path); end
end

function response = make_response(runner,action)
response = struct('status','pending','action',action,'branch',runner.branch, ...
    'step',runner.state.step,'time_s',runner.state.t,'energy',runner.get_energy());
end

function write_json(path,value)
tmp = [tempname(fileparts(path)),'.json'];
cleanup = onCleanup(@() delete_if_exists(tmp));
text = jsonencode(value);
fid = fopen(tmp,'w','n','UTF-8');
if fid < 0, error('matlab_structure_worker:Response','Cannot open response temp file.'); end
fwrite(fid,text,'char'); fwrite(fid,newline,'char'); fclose(fid);
movefile(tmp,path,'f');
clear cleanup
end

function delete_if_exists(path)
if exist(path,'file'), delete(path); end
end
