"""Deny-by-default public inventory and deterministic manual-install archive."""
import argparse,ast,hashlib,json,os,re,runpy,stat,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def verify(root):
    allowed=set(json.loads((root/'ci/public-files.json').read_text()))
    expected=json.loads((root/'ci/component-files.json').read_text())
    generated={'build/xparkle-rvlevel-0.5.0.zip','build/SHA256SUMS','build/component-files.json','ci-results/product-tests.xml'}
    actual=set()
    for folder,dirs,files in os.walk(root,followlinks=False):
        base=Path(folder)
        if base==root and '.git' in dirs:dirs.remove('.git')
        for name in dirs+files:
            path=base/name;mode=path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):raise ValueError('Link or special object')
        for name in files:
            path=base/name;rel=path.relative_to(root).as_posix()
            if rel in generated:continue
            actual.add(rel)
            if path.suffix not in ('.png','.zip'):
                text=path.read_text()
                forbidden=(r'/'+'Users/',r'/'+'private/',r'homeassistant'+r'[.]local',r'(?i)AGENTS'+r'[.]md|_'+'bmad',r'gh[pousr]_[A-Za-z0-9]{20,}',r'-----BEGIN '+r'(?:RSA |EC |OPENSSH )?PRIVATE KEY'+r'-----')
                for pattern in forbidden:
                    if re.search(pattern,text):raise ValueError('Private or secret-like content: '+rel)
    if actual!=allowed:raise ValueError('Missing or unexpected public file')
    component=root/'custom_components/xparkle_rvlevel'
    found={f.relative_to(component).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in component.rglob('*') if f.is_file()}
    if found!=expected:raise ValueError('Component changed after review inventory')
    generator=runpy.run_path(str(root/'script/build_frontend.py'))
    if (component/'frontend/xparkle-card.js').read_bytes()!=generator['assemble'](root).encode():raise ValueError('Frontend source and generated bundle differ')
    manifest=json.loads((component/'manifest.json').read_text())
    if manifest['version']!='0.5.0' or manifest['codeowners']!=['@mimyll'] or manifest['issue_tracker']!='https://github.com/mimyll/xparkle-rvlevel/issues':raise ValueError('Public metadata mismatch')
    if json.loads((root/'hacs.json').read_text()).get('zip_release',False):raise ValueError('Expected repository delivery, not zip_release')
    for f in component.rglob('*.py'):ast.parse(f.read_text())
    for f in component.rglob('*.json'):json.loads(f.read_text())
    return found

def build(root):
    inventory=verify(root);out=root/'build';out.mkdir(exist_ok=True)
    name='xparkle-rvlevel-0.5.0.zip'
    with zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for rel in sorted(inventory):
            info=zipfile.ZipInfo('custom_components/xparkle_rvlevel/'+rel,(1980,1,1,0,0,0));info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,(root/'custom_components/xparkle_rvlevel'/rel).read_bytes())
    (out/'component-files.json').write_text(json.dumps(inventory,indent=2,sort_keys=True)+'\n')
    (out/'SHA256SUMS').write_text(hashlib.sha256((out/name).read_bytes()).hexdigest()+'  '+name+'\n'+hashlib.sha256((out/'component-files.json').read_bytes()).hexdigest()+'  component-files.json\n')
    print('Public inventory and deterministic component archive verified.')

if __name__=='__main__':build(ROOT)
