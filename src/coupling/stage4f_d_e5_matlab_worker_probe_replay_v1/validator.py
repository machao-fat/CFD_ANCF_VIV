from pathlib import Path
def validate_probe(p):
    req=('return_code','release','arch','license','application_service','temp','tmp','tmpdir','prefdir')
    if any(k not in p for k in req): return False
    return p['return_code']==0 and p['release']=='2021b' and p['arch']=='win64' and p['license']==1 and p['application_service'] is True and all(str(p[k]).lower().startswith('d:') for k in ('temp','tmp','tmpdir','prefdir'))
def validate_replay(r):
    return r.get('return_code')==0 and r.get('output_exists') and r.get('fresh') and r.get('identity_ok') and r.get('finite') and r.get('attempts')==1
def may_replay(probe): return validate_probe(probe)
