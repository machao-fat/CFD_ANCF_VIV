import json
def exact_int(value,name,minimum=0):
 try:
  import numpy as np
  if isinstance(value,np.integer):value=int(value)
 except ImportError:pass
 if isinstance(value,bool) or not isinstance(value,int):raise ValueError(f'{name} must be a JSON integer')
 if value<minimum:raise ValueError(f'{name} below minimum')
 return value
def roundtrip(value):
 v=exact_int(value,'value',-(1<<4096));loaded=json.loads(json.dumps({'v':v}))['v'];return loaded,type(loaded).__name__,loaded==v
