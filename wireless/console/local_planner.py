"""Private planner configuration; release defaults require no personal settings."""
import json
import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / '.runtime/planner.json'
DEFAULTS = {'provider': 'codex', 'transport': 'app_server', 'model': None,
            'effort': 'low', 'keep_awake': False}

def settings():
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text()))
    if os.environ.get('IPHONE_MODEL'):
        cfg['model'] = os.environ['IPHONE_MODEL']
    if cfg.get('provider') != 'codex' or cfg.get('hybrid'):
        raise ValueError('此发布版仅支持 Codex；本地实验配置不兼容，请删除旧 planner.json。')
    return cfg
