function stage4f_v2_write_json(filepath,value)
%STAGE4F_V2_WRITE_JSON UTF-8 JSON with finite-value enforcement.
text = jsonencode(value);
if contains(text,'NaN') || contains(text,'Infinity')
    error('stage4f_v2_write_json:Finite','JSON contains NaN or Infinity.');
end
fid = fopen(filepath,'w','n','UTF-8');
if fid < 0, error('stage4f_v2_write_json:Open','Cannot open %s.',filepath); end
cleanup = onCleanup(@() fclose(fid));
fwrite(fid,text,'char');
fwrite(fid,newline,'char');
clear cleanup
end

