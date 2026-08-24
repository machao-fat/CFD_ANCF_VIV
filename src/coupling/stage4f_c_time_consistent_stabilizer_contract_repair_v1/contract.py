from __future__ import annotations
import hashlib, json, math
from decimal import Decimal, localcontext
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'results/23_stage4f_c_time_consistent_stabilizer_design_v1/candidate_protocol_contract.json'
SOURCE_SHA256='d24b089822478160986b93584f391dbe636de164994411938da5b5e850e77369'
SOURCE_SCHEMA='stage4f-c-time-consistent-stabilizer-candidate/1.0'

class ContractError(RuntimeError): pass
def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _unique(pairs):
 d={}
 for k,v in pairs:
  if k in d: raise ContractError(f'duplicate JSON field: {k}')
  d[k]=v
 return d
def load_contract(path=SOURCE, expected_hash=SOURCE_SHA256):
 p=Path(path)
 if sha256(p)!=expected_hash: raise ContractError('contract hash mismatch')
 try: data=json.loads(p.read_text(encoding='utf-8'),parse_float=Decimal,parse_constant=lambda x:(_ for _ in ()).throw(ContractError('nonfinite JSON')),object_pairs_hook=_unique)
 except (ValueError,json.JSONDecodeError) as e: raise ContractError(str(e)) from e
 if data.get('schema')!=SOURCE_SCHEMA: raise ContractError('schema mismatch')
 rows=[x for x in data.get('candidates',[]) if x.get('id')=='B_exponential_time']
 if len(rows)!=1 or 'tau_s' not in rows[0]: raise ContractError('unique tau source missing')
 tau=rows[0]['tau_s']
 if not isinstance(tau,Decimal) or not tau.is_finite() or tau<=0: raise ContractError('invalid decimal tau')
 raw='0.023728053952574758'
 if tau!=Decimal(raw): raise ContractError('tau differs from immutable authorized decimal')
 return {'source_path':str(p.resolve()),'source_sha256':expected_hash,'source_schema':SOURCE_SCHEMA,'tau_raw_decimal':raw,'tau_canonical_decimal':format(tau,'f')}
def verify_math(contract):
 tau=Decimal(contract['tau_canonical_decimal']); tol=Decimal('5e-17')
 with localcontext() as ctx:
  ctx.prec=50
  def alpha(dt):
   d=Decimal(str(dt))
   if not d.is_finite() or d<=0: raise ContractError('dt must be finite and positive')
   return Decimal(1)-(-d/tau).exp()
  a=alpha('0.0025'); h=alpha('0.00125'); old=Decimal(1)-a; combined=(Decimal(1)-h)**2
  errors={'alpha_abs':abs(a-Decimal('.1')),'old_weight_abs':abs(old-Decimal('.9')),'half_composition_abs':abs(combined-Decimal('.9')),'exp_abs':abs((-Decimal('.0025')/tau).exp()-Decimal('.9'))}
  if any(v>tol for v in errors.values()): raise ContractError('authorized math exceeds strict tolerance')
  return {'formula':'1-exp(-dt/tau)','alpha_0_0025':str(a),'alpha_0_00125':str(h),'old_weight_0_0025':str(old),'half_old_weight_squared':str(combined),'absolute_errors':{k:str(v) for k,v in errors.items()},'relative_alpha_error':str(errors['alpha_abs']/Decimal('.1')),'absolute_tolerance':str(tol),'future_force_access':False,'equal_elapsed_decay_verified':True}
def canonical(contract,math_audit):
 payload={'schema':'0.2.1+stabilizer.time-consistent.1','source':contract,'math':math_audit,'algorithm':'first_order_load_relaxation_physical_time','tick_hz':1000000000,'raw_force_immutable':True}
 encoded=json.dumps(payload,sort_keys=True,separators=(',',':')).encode(); payload['canonical_sha256']=hashlib.sha256(encoded).hexdigest(); return payload
