"""Public delivery boundaries: malformed inventories, metadata and CI privilege."""
import importlib.util,json,shutil
from pathlib import Path
import pytest
import yaml
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('release_verifier',ROOT/'script/verify_release.py')
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)

@pytest.mark.parametrize('mutation',['extra','link','secret','version','component','frontend_source'])
def test_public_boundary_rejects_planted_drift(tmp_path,mutation):
    copy=tmp_path/'public';shutil.copytree(ROOT,copy,ignore=shutil.ignore_patterns('.git','__pycache__','build','ci-results'))
    if mutation=='extra':(copy/('AGENTS'+'.md')).write_text('private method')
    elif mutation=='link':(copy/'extra').symlink_to(copy/'README.md')
    elif mutation=='secret':(copy/'README.md').write_text('/'+'Users/'+'private-owner/project')
    elif mutation=='version':
        f=copy/'custom_components/xparkle_rvlevel/manifest.json';data=json.loads(f.read_text());data['version']='99.0.0';f.write_text(json.dumps(data))
    elif mutation=='frontend_source':
        f=copy/'frontend/card-behavior.js';f.write_text(f.read_text()+'\n// drift\n')
    else:
        f=copy/'custom_components/xparkle_rvlevel/session.py';f.write_text(f.read_text()+'\n# drift\n')
    with pytest.raises(ValueError):verifier.verify(copy)


def test_public_workflow_limits_write_to_explicit_main_release():
    workflow=yaml.load((ROOT/'.github/workflows/validate.yml').read_text(),Loader=yaml.BaseLoader)
    assert workflow['permissions']=={'contents':'read'}
    assert 'pull_request_target' not in workflow['on']
    jobs=workflow['jobs'];publish=jobs['publish']
    assert publish['permissions']=={'contents':'write'}
    assert "github.event_name == 'workflow_dispatch'" in publish['if']
    assert "inputs.publish" in publish['if'] and "refs/heads/main" in publish['if']
    assert set(publish['needs'])=={'product','frontend','hassfest','hacs'}
    import re
    for name,job in jobs.items():
        if name!='publish':assert 'permissions' not in job
        for step in job['steps']:
            if 'uses' in step:assert re.fullmatch(r'[^@]+@[a-f0-9]{40}',step['uses'])
            if step.get('uses','').startswith('actions/checkout@'):assert step['with']['persist-credentials']=='false'


def test_old_fixture_has_reviewed_identity_and_component_only_layout():
    import hashlib,zipfile
    fixture=ROOT/'tests/fixtures/component-0.3.0.zip'
    assert hashlib.sha256(fixture.read_bytes()).hexdigest()=='dae9f7cf516570da9b5dac20ca0ceebdfbd9f7ad3da4021bbdeaed18b06940b7'
    with zipfile.ZipFile(fixture) as z:
        assert len(z.namelist())==25
        assert all(name.startswith('custom_components/xparkle_rvlevel/') and '..' not in Path(name).parts for name in z.namelist())
