"""Single authoritative OpenFOAM-10 displacementLaplacian case contract."""
from __future__ import annotations
import re
from pathlib import Path
from coupling.moving_mesh_patch_compatibility_v1.audit import audit as patch_audit

SCHEMA='moving-mesh-openfoam10-case-contract-v1'
REQUIRED_SOLVERS=('cellDisplacement','cellDisplacementFinal')
REQUIRED_BINDINGS={'namePointDisplacement':'pointDisplacement','nameCellDisplacement':'cellDisplacement'}

def _block(text:str,name:str) -> tuple[int,int] | None:
    match=re.search(rf'\b{re.escape(name)}\s*\{{',text)
    if not match:return None
    start=text.find('{',match.start()); depth=0
    for i in range(start,len(text)):
        depth += text[i]=='{'; depth -= text[i]=='}'
        if depth==0:return start,i
    raise RuntimeError(f'unterminated dictionary block {name}')

def ensure_solver_entries(path:Path) -> None:
    """Add both required entries while inheriting frozen cellMotionUx settings."""
    text=path.read_text(encoding='utf-8'); solvers=_block(text,'solvers')
    if solvers is None: raise RuntimeError('fvSolution lacks solvers dictionary')
    if _block(text,'cellMotionUx') is None: raise RuntimeError('fvSolution lacks frozen cellMotionUx source settings')
    additions=[]
    if _block(text,'cellDisplacement') is None:
        additions += ['    cellDisplacement','    {','        $cellMotionUx;','    }']
    if _block(text,'cellDisplacementFinal') is None:
        additions += ['    cellDisplacementFinal','    {','        $cellDisplacement;','        relTol 0;','    }']
    elif '$cellMotionUx;' in text[_block(text,'cellDisplacementFinal')[0]:_block(text,'cellDisplacementFinal')[1]+1]:
        a,b=_block(text,'cellDisplacementFinal'); text=text[:a]+'{\n        $cellDisplacement;\n        relTol 0;\n    }'+text[b+1:]
    if additions:
        solvers=_block(text,'solvers'); assert solvers
        text=text[:solvers[1]]+'\n'+'\n'.join(additions)+'\n'+text[solvers[1]:]
    with path.open('w',encoding='utf-8',newline='\n') as out: out.write(text)

def preflight(case:Path, field_directory:str) -> dict[str,object]:
    patch=patch_audit(case,field_directory); issues=list(patch['issues'])
    dynamic=(case/'constant/dynamicMeshDict').read_text(encoding='utf-8',errors='replace')
    precice=(case/'system/preciceDict').read_text(encoding='utf-8',errors='replace')
    fv=(case/'system/fvSolution').read_text(encoding='utf-8',errors='replace')
    if 'displacementLaplacian' not in dynamic: issues.append('active mover is not displacementLaplacian')
    for name,want in REQUIRED_BINDINGS.items():
        m=re.search(rf'\b{name}\s+(\w+)\s*;',precice)
        if not m or m.group(1)!=want: issues.append(f'{name} binding is not {want}')
    solvers=_block(fv,'solvers')
    if solvers is None: issues.append('missing fvSolution/solvers')
    else:
        for name in REQUIRED_SOLVERS:
            if _block(fv,name) is None: issues.append(f'missing fvSolution solver {name}')
    return {'schema_version':SCHEMA,'case':str(case),'active_motion_solver':'displacementLaplacian' if 'displacementLaplacian' in dynamic else 'other','required_fields':['pointDisplacement','cellDisplacement'],'required_solvers':list(REQUIRED_SOLVERS),'required_bindings':REQUIRED_BINDINGS,'patch_compatibility':patch,'issues':issues,'MOVING_MESH_CASE_PREFLIGHT':'PASS' if not issues else 'FAIL'}
