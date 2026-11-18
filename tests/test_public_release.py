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


async def test_native_config_entry_only_schema_reports_yaml_without_starting(tmp_path,caplog,monkeypatch):
    from unittest.mock import AsyncMock
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import issue_registry as ir
    import custom_components.xparkle_rvlevel as integration

    hass=HomeAssistant(str(tmp_path))
    setup=AsyncMock();entry_setup=AsyncMock()
    monkeypatch.setattr(integration,'async_setup',setup)
    monkeypatch.setattr(integration,'async_setup_entry',entry_setup)
    registry=ir.async_get(hass)
    unrelated={'example':{'value':'keep'}}
    assert integration.CONFIG_SCHEMA(unrelated) is unrelated
    assert not registry.issues and not caplog.records
    for unsupported in ({},{'address':'00:00:00:00:00:01'}):
        config={**unrelated,'xparkle_rvlevel':unsupported}
        assert integration.CONFIG_SCHEMA(config) is config
        assert config['example']==unrelated['example']
        issue=registry.async_get_issue('homeassistant','config_entry_only_xparkle_rvlevel')
        assert issue is not None and issue.severity is ir.IssueSeverity.ERROR
        assert issue.translation_key=='config_entry_only' and issue.issue_domain=='xparkle_rvlevel'
    assert 'does not support YAML setup' in caplog.text
    assert 'xparkle_rvlevel' not in hass.data
    setup.assert_not_called();entry_setup.assert_not_called()
    await hass.async_stop(force=True)


def test_package_protocol_import_and_decode_without_homeassistant():
    import subprocess,sys
    program='''
import sys,importlib.abc
class NoHA(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='homeassistant' or fullname.startswith('homeassistant.'):
            raise AssertionError('unexpected_homeassistant_dependency')
sys.meta_path.insert(0,NoHA())
from custom_components.xparkle_rvlevel.protocol import decode
result=decode(bytes((0,0,9,1,0,50,100)))
assert (result.pitch_magnitude,result.roll_magnitude,result.battery)==(.09,.5,100)
assert result.uphill is False and result.left_tilt is True
assert not any(name=='homeassistant' or name.startswith('homeassistant.') for name in sys.modules)
'''
    subprocess.run([sys.executable,'-S','-c',program],cwd=ROOT,check=True,capture_output=True,text=True,timeout=10)
