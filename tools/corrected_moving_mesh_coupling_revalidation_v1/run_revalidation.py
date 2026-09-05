"""Run corrected fresh 1 s smoke then conditional fresh 20 s revalidation."""
from __future__ import annotations
import hashlib, importlib.util, json, math, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.ancf_newton_evidence_v1 import validate_records
from coupling.openfoam_numerical_quality_contract_v2 import audit_log,evaluate_quality
from coupling.slice_independence_audit_v1.audit import parse_forces,sha256
HERE=Path(__file__).parent; V1=ROOT/'tools/three_slice_force_contract_smoke_v1/run_smoke.py'; QUALITY=ROOT/'tools/numerical_quality_evidence_closure_v1/openfoam_numerical_quality_contract_v2.json'
NUM=r'[-+0-9.eE]+'
def load_launcher(runtime,results,contract,duration):
 s=importlib.util.spec_from_file_location('corrected_launcher',V1); m=importlib.util.module_from_spec(s); assert s.loader; s.loader.exec_module(m)
 m.RUNTIME,m.RESULTS,m.CONTRACT=runtime,results,contract
 m.CONTROL=m.CONTROL.replace('endTime 1;',f'endTime {duration:g};').replace('writeInterval 1;','writeInterval 20;')
 xml=m.xml; m.xml=lambda sid: xml(sid).replace('<max-time value="1"/>',f'<max-time value="{duration:g}"/>')
 return m
def patch_block(text,name):
 m=re.search(rf'\b{name}\s*\{{',text); assert m, name; p=text.find('{',m.start()); d=0
 for i in range(p,len(text)):
  d += text[i]=='{'; d -= text[i]=='}'
  if d==0:return text[p+1:i]
 raise RuntimeError('unterminated block')
def vectors_from_block(block):
 vals=re.findall(r'\(\s*(%s)\s+(%s)\s+(%s)\s*\)'%(NUM,NUM,NUM),block)
 if vals:return [[float(x) for x in v] for v in vals]
 u=re.search(r'value\s+uniform\s+\(\s*(%s)\s+(%s)\s+(%s)\s*\)'%(NUM,NUM,NUM),block)
 return [[float(x) for x in u.groups()]] if u else []
def mesh_centroid(case,time):
 b=(case/'constant/polyMesh/boundary').read_text(); q=patch_block(b,'cylinder'); start=int(re.search(r'startFace\s+(\d+)',q).group(1)); n=int(re.search(r'nFaces\s+(\d+)',q).group(1))
 pts=[[float(x) for x in v] for v in re.findall(r'\(\s*(%s)\s+(%s)\s+(%s)\s*\)'%(NUM,NUM,NUM),(case/time/'polyMesh/points').read_text())]
 faces=[]
 for line in (case/'constant/polyMesh/faces').read_text().splitlines():
  z=re.match(r'\s*\d+\(([^)]*)\)',line)
  if z:faces.append([int(x) for x in z.group(1).split()])
 chosen=faces[start:start+n]; cs=[[sum(pts[i][a] for i in f)/len(f) for a in range(3)] for f in chosen]
 return [sum(x[a] for x in cs)/len(cs) for a in range(3)]
def point_centroid(case,time):
 block=patch_block((case/time/'pointDisplacement').read_text(),'cylinder'); vs=vectors_from_block(block)
 if not vs:raise RuntimeError('point displacement missing')
 return [sum(v[a] for v in vs)/len(vs) for a in range(3)]
def arr(path,vector):
 t=path.read_text(); mark='internalField   nonuniform List<vector>' if vector else 'internalField   nonuniform List<scalar>'; rest=t[t.index(mark)+len(mark):]; n=int(re.search(r'\s*(\d+)\s*\(',rest).group(1)); rest=rest[rest.index('(')+1:]
 if vector:return [[float(x) for x in v] for v in re.findall(r'\(\s*(%s)\s+(%s)\s+(%s)\s*\)'%(NUM,NUM,NUM),rest)[:n]]
 return [float(x) for x in rest.split(')',1)[0].split()[:n]]
def l2(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip((z for r in a for z in r) if a and isinstance(a[0],list) else a,(z for r in b for z in r) if b and isinstance(b[0],list) else b)))
def mean(x):return sum(x)/len(x)
def rms(x):return math.sqrt(mean([z*z for z in x]))
def audit(runtime,results,contract,code):
 c=json.loads(contract.read_text()); n=int(c['number_of_steps']); dt=float(c['dt_s']); rows=[json.loads(x) for x in (runtime/'records.jsonl').read_text().splitlines() if x]; newton=[json.loads(x) for x in (runtime/'newton_evidence.jsonl').read_text().splitlines() if x]; qcon=json.loads(QUALITY.read_text()); cases=[runtime/'cases'/f'slice_{i:04d}' for i in range(3)]
 quality={};
 for i,case in enumerate(cases): quality[str(i)]=evaluate_quality(audit_log(runtime/'logs'/f'fluid_{i:04d}.stdout',case/'system/fvSolution'),qcon)
 try: ns=validate_records(newton,expected_steps=n)
 except Exception as e: ns={'status':'fail','error':str(e)}
 mc=c.get('moving_mesh_contract')
 if mc is None:
  # Later patch-consistency contracts retain the same frozen tolerance under
  # a narrower schema; normalize it without mutating the frozen contract.
  p=c['moving_mesh_patch_contract']; mc={'reference_cylinder_centroid_xyz_m':[0.0,0.0,0.5],'mesh_motion_error_tolerance_m':p['mesh_tracking_tolerance_m'],'point_displacement_error_tolerance_m':p['mesh_tracking_tolerance_m'],'distinct_motion_threshold_m':1e-8,'distinct_geometry_threshold_m':1e-9,'field_comparison_times_s':[0.1,0.5,1.0] if n==200 else [1.0,5.0,10.0,15.0,20.0]}
 snapshots=[k for k in range(20,n+1,20)]; mesh=[]; meshok=True; geomdistinct=True
 for step in snapshots:
  t=f'{step*dt:g}'; geo=[]; struct=[]
  for i,case in enumerate(cases):
   actual=mesh_centroid(case,t); point=point_centroid(case,t); m=rows[step-1]['motion'][i]; disp=[float(m[f'{a}x_m'] if False else m[f'u{a}_m']) for a in 'xyz']; expected=[mc['reference_cylinder_centroid_xyz_m'][a]+disp[a] for a in range(3)]; err=math.sqrt(sum((actual[a]-expected[a])**2 for a in range(3))); perr=math.sqrt(sum((point[a]-disp[a])**2 for a in range(3))); meshok &= err<=mc['mesh_motion_error_tolerance_m'] and perr<=mc['point_displacement_error_tolerance_m']; geo.append(actual); struct.append(disp); mesh.append({'step':step,'time_s':step*dt,'slice_id':i,'structure_displacement_xyz_m':disp,'received_precice_displacement_xyz_m':point,'cylinder_pointDisplacement_xyz_m':point,'actual_cylinder_centroid_xyz_m':actual,'expected_cylinder_centroid_xyz_m':expected,'mesh_motion_error_m':err,'point_displacement_error_m':perr,'mesh_points_sha256':sha256(case/t/'polyMesh/points')})
  for a,b in ((0,1),(0,2),(1,2)):
   sd=math.sqrt(sum((struct[a][j]-struct[b][j])**2 for j in range(3))); gd=math.sqrt(sum((geo[a][j]-geo[b][j])**2 for j in range(3)))
   if sd>mc['distinct_motion_threshold_m'] and gd<=mc['distinct_geometry_threshold_m']:geomdistinct=False
 forcepaths=[case/'postProcessing/cylinderForces/0/forces.dat' for case in cases]; force=[parse_forces(p) for p in forcepaths]; fymax=max(max(x[t]['total_N'][1] for x in force)-min(x[t]['total_N'][1] for x in force) for t in set(force[0])&set(force[1])&set(force[2]))
 field={}
 for time in mc['field_comparison_times_s']:
  t=f'{time:g}'; u=[arr(x/t/'U',True) for x in cases]; p=[arr(x/t/'p',False) for x in cases]; field[t]={'U_l2_pairwise':{'0-1':l2(u[0],u[1]),'0-2':l2(u[0],u[2]),'1-2':l2(u[1],u[2])},'p_l2_pairwise':{'0-1':l2(p[0],p[1]),'0-2':l2(p[0],p[2]),'1-2':l2(p[1],p[2]),},'U_sha256':[sha256(x/t/'U') for x in cases],'p_sha256':[sha256(x/t/'p') for x in cases]}
 moments=[r['moment_audit'] for r in rows]; mapping=max(float(x['force_error_absolute_N']) for x in moments)<=1e-8 and max(float(x['moment_error_absolute_Nm']) for x in moments)<=1e-7 and max(float(x['moment_error_normalized_v2']) for x in moments)<=1e-12
 finite=all(all(math.isfinite(float(r['motion'][i]['uy_m'])) for i in range(3)) for r in rows); forcechain=all(all(abs(float(x[f'force_{a}_N'])-float(x[f'force_2d_{a}_Npm'])*float(x['slice_length_m']))<=1e-12 for a in 'xyz') for r in rows for x in r['loads'])
 rawidentical=len({p.read_bytes() for p in forcepaths})==1; checks={'windows':len(rows)==n and code==0,'force_contract':forcechain,'mapping':mapping,'quality_v2':all(x['status']=='pass' for x in quality.values()),'newton':ns.get('status')=='pass' and len(newton)==2*n,'moving_mesh_application':meshok,'slice_geometry_independence':geomdistinct,'finite':finite};
 if n==4000: checks['nonidentical_raw_force_under_distinct_motion']=not rawidentical
 result={'gate':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'mesh_records':mesh,'field_evidence':field,'raw_force_sha256':[sha256(p) for p in forcepaths],'raw_forces_byte_identical':rawidentical,'max_pairwise_Fy_difference_N':fymax,'quality':quality,'newton':ns,'row_count':len(rows)}; results.mkdir(parents=True,exist_ok=True); (results/'gate.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); return result
def phase(label):
 contract=HERE/f'corrected_moving_mesh_coupling_revalidation_v1_{label}_contract.json'; c=json.loads(contract.read_text()); runtime=ROOT/'runtime'/c['run_id']; results=ROOT/'results'/c['run_id']; launcher=load_launcher(runtime,results,contract,float(c['duration_s'])); cases=launcher.prepare(); return audit(runtime,results,contract,launcher.launch(cases))
def main():
 a=phase('1s'); print(json.dumps({'phase_A':a['gate']}));
 if a['gate']!='PASS':return 1
 b=phase('20s'); print(json.dumps({'phase_B':b['gate']})); return 0 if b['gate']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
