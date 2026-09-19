from pathlib import Path
import json, shutil

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
basic = DATA / '基础物品'
old = DATA / '物品'
alchemy = DATA / '炼丹'
if basic.exists() and not old.exists():
    shutil.copytree(basic, old)
    shutil.move(str(alchemy / '内容' / '丹药'), str(old / '内容' / '丹药'))
    shutil.rmtree(basic)
    m = old / '组件.json'; v=json.loads(m.read_text(encoding='utf-8')); v['组件']='物品'; v['读取规则']=[{**r, '路径': r['路径'].replace('基础基础物品/','基础物品/'), '实体类别': '物品' if r.get('实体类别')=='基础物品' else r.get('实体类别'), '编号类别': '物品' if r.get('编号类别')=='基础物品' else r.get('编号类别')} for r in v['读取规则']]; v['读取规则'].append({'数据集':'物品','路径':'物品/基础物品/内容/丹药/*/*.json','结构':'编号实体列表','实体类别':'物品','编号类别':'物品'}); m.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    am=alchemy/'组件.json'; av=json.loads(am.read_text(encoding='utf-8')); av['读取规则']=[r for r in av['读取规则'] if r.get('数据集')!='丹药']; am.write_text(json.dumps(av,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    entry=DATA/'基础/读取规则.json'; e=json.loads(entry.read_text(encoding='utf-8')); e['扫描目录']=['物品' if x=='基础物品' else x for x in e['扫描目录']]; e['文件名唯一']=['物品' if x=='基础物品' else x for x in e['文件名唯一']]; e['资源池字段']={k:('物品' if v=='基础物品' else v) for k,v in e['资源池字段'].items()}; entry.write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
