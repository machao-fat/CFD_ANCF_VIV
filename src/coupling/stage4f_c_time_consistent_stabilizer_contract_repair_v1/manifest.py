from __future__ import annotations
import hashlib
from dataclasses import dataclass,asdict
from pathlib import Path
class ManifestError(RuntimeError): pass
@dataclass(frozen=True)
class RawForceSnapshotManifest:
 path:str; canonical_path:str; sha256:str; file_size:int; mtime_ns:int; run_id:str; case_id:str; global_step:int; slice_id:int; integer_tick:int; force_schema:str; artifact_creation_transaction:str; consumed_transaction:str; immutable:bool=True; kind:str='raw'
 @classmethod
 def capture(cls,path,root,**identity):
  p=Path(path).resolve(); r=Path(root).resolve()
  try:p.relative_to(r)
  except ValueError:raise ManifestError('snapshot path escapes root')
  if not p.is_file():raise ManifestError('missing snapshot')
  st=p.stat(); digest=hashlib.sha256(p.read_bytes()).hexdigest()
  required=['run_id','case_id','global_step','slice_id','integer_tick','force_schema','artifact_creation_transaction','consumed_transaction']
  if any(k not in identity or identity[k] in ('',None) for k in required):raise ManifestError('snapshot identity incomplete')
  return cls(str(p),str(p),digest,st.st_size,st.st_mtime_ns,**identity)
 def validate(self,root,**expected):
  if self.kind!='raw' or not self.immutable:raise ManifestError('raw/applied kind or immutability mismatch')
  for k,v in expected.items():
   if getattr(self,k)!=v:raise ManifestError(f'identity mismatch: {k}')
  p=Path(self.canonical_path).resolve(); r=Path(root).resolve()
  try:p.relative_to(r)
  except ValueError:raise ManifestError('snapshot path escapes root')
  if str(p)!=self.path or not p.is_file():raise ManifestError('snapshot missing/path mismatch')
  st=p.stat()
  if st.st_size!=self.file_size or st.st_mtime_ns!=self.mtime_ns:raise ManifestError('snapshot size/mtime changed')
  if hashlib.sha256(p.read_bytes()).hexdigest()!=self.sha256:raise ManifestError('snapshot hash changed')
  return asdict(self)
