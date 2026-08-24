class IdentityError(RuntimeError): pass
def audit_engine(engine,expected):
 values={'factory':engine.run_id,'scheduler':engine.scheduler.run_id,'processes':[p.run_id for p in engine.processes]}
 if values['factory']!=expected or values['scheduler']!=expected or any(x!=expected for x in values['processes']):raise IdentityError('factory object graph identity mismatch')
 return values
def validate_manifest_transactions(items,run_id,step,tick):
 seen=set()
 for item in items:
  expected=f'{run_id}:{step}:{int(item["slice_id"])}:{tick}:create'
  if item.get('artifact_creation_transaction')!=expected:raise IdentityError('stale/default creation transaction')
  consumed=item.get('consumed_transaction')
  if not isinstance(consumed,str) or not consumed or consumed in seen:raise IdentityError('missing/duplicate consumed transaction')
  seen.add(consumed)
 return True
