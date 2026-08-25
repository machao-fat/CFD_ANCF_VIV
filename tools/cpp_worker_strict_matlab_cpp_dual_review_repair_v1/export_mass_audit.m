function export_mass_audit(source_mat, output_json)
% Export immutable MATLAB mass bytes for offline C++ input audit only.
loaded = load(char(source_mat), 'state');
if ~isfield(loaded, 'state') || ~isfield(loaded.state, 'model')
    error('stage186:MassSource', 'invalid source state');
end
M = double(loaded.state.model.mass_matrix);
if any(~isfinite(M(:))) || size(M,1) ~= size(M,2)
    error('stage186:MassSchema', 'invalid mass matrix');
end
bytes = typecast(M(:), 'uint8');
md = java.security.MessageDigest.getInstance('SHA-256');
md.update(int8(bytes(:))); raw = md.digest(); u = zeros(1,numel(raw),'uint8');
for k=1:numel(raw), v=double(raw(k)); if v<0,v=v+256;end, u(k)=uint8(v); end
out = struct('rows',size(M,1),'cols',size(M,2),'layout','MATLAB column-major raw float64', ...
    'mass_sha256',lower(reshape(dec2hex(u,2).',1,[])), ...
    'mass_values',M(:).');
encoded = jsonencode(out); fid=fopen(char(output_json),'w','n','UTF-8');
if fid<0,error('stage186:MassOutput','cannot open output');end
fwrite(fid,[encoded newline],'char'); fclose(fid);
end
