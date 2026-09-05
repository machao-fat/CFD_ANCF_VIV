from __future__ import annotations
import re
from pathlib import Path

class CompatibilityError(RuntimeError): pass
def block(text: str, name: str) -> str:
    m=re.search(rf'\b{re.escape(name)}\s*\{{',text)
    if not m: raise CompatibilityError(f'missing patch {name}')
    i=text.find('{',m.start()); depth=0
    for j in range(i,len(text)):
        depth += text[j]=='{'; depth -= text[j]=='}'
        if depth==0:return text[i+1:j]
    raise CompatibilityError(f'unterminated patch {name}')
def inventory(boundary: Path) -> dict[str,str]:
    text=boundary.read_text(encoding='utf-8',errors='replace'); result={}
    for name in re.findall(r'(?m)^\s*([A-Za-z_]\w*)\s*\{',text):
        value=block(text,name); m=re.search(r'\btype\s+(\w+)\s*;',value)
        if m: result[name]=m.group(1)
    if not result: raise CompatibilityError('empty boundary inventory')
    return result
def required_fields(case: Path) -> list[str]:
    dynamic=(case/'constant/dynamicMeshDict').read_text(encoding='utf-8',errors='replace'); precice=(case/'system/preciceDict').read_text(encoding='utf-8',errors='replace')
    fields=[]
    if 'displacementLaplacian' in dynamic: fields.append('pointDisplacement')
    for key in ('namePointDisplacement','nameCellDisplacement'):
        m=re.search(rf'\b{key}\s+(\w+)\s*;',precice)
        if m and m.group(1)!='unused': fields.append(m.group(1))
    return list(dict.fromkeys(fields))
def audit(case: Path) -> dict[str,object]:
    patches=inventory(case/'constant/polyMesh/boundary'); fields=required_fields(case); issues=[]; details={}
    for field in fields:
        path=case/'0'/field
        if not path.is_file(): issues.append(f'missing field {field}'); continue
        text=path.read_text(encoding='utf-8',errors='replace'); row={}
        for patch,mesh_type in patches.items():
            try: value=block(text,patch)
            except CompatibilityError: issues.append(f'{field}: missing {patch}'); continue
            m=re.search(r'\btype\s+(\w+)\s*;',value)
            if not m: issues.append(f'{field}: missing type on {patch}'); continue
            ftype=m.group(1); row[patch]=ftype
            if mesh_type in ('symmetryPlane','empty') and ftype!=mesh_type: issues.append(f'{field}/{patch}: mesh={mesh_type}, field={ftype}')
        details[field]=row
    return {'case':str(case),'mesh_patch_inventory':patches,'required_motion_fields':fields,'field_patch_types':details,'issues':issues,'MESH_FIELD_PATCH_COMPATIBILITY':'PASS' if not issues else 'FAIL'}
