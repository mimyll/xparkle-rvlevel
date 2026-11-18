"""Build the optional card from repository-owned UTF-8 sources."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def assemble(root):
    component=root/'custom_components/xparkle_rvlevel'
    version=json.loads((component/'manifest.json').read_text())['version']
    template=(root/'frontend/card-template.html').read_text()
    behavior=(root/'frontend/card-behavior.js').read_text()
    return '/* Xparkle RV level '+version+'. Optional public card. */\nconst TEMPLATE = '+json.dumps(template,ensure_ascii=False)+';\n'+behavior

if __name__=='__main__':
    (ROOT/'custom_components/xparkle_rvlevel/frontend/xparkle-card.js').write_text(assemble(ROOT))
