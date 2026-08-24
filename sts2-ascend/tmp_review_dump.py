import json, glob

OUT = open(r'D:\workspace\slay-the-spire-vivhite-mod\sts2-ascend\tmp_review_dump.txt', 'w', encoding='utf-8')

RUNS = {
    '374': 'HXLXGQC548M2',
    '375': 'PLQH2NR9N5JU',
    '376': 'DB06WGLME1BN',
    '377': 'BNSJMBDR4GWA',
}

for tag, rid in RUNS.items():
    p = glob.glob(f'sts2-ascend/knowledge/runs/*_{rid}.json')[0]
    d = json.load(open(p, encoding='utf-8'))
    OUT.write('=' * 40 + f'run {tag} {rid} floor={d["floor"]} victory={d["victory"]}\n')
    for i, dec in enumerate(d['decisions']):
        scr = dec.get('screen', '')
        act = dec.get('action', '')
        keep_screens = ('MAP', 'REST', 'SHOP', 'REWARD', 'CARD_SELECTION', 'GAME_OVER', 'EVENT')
        if scr in keep_screens or act in ('use_potion',):
            s = json.dumps(dec, ensure_ascii=False)
            OUT.write(f'[{i}] {s[:500]}\n')
    OUT.write('---- combat_notes:' + json.dumps(d.get('combat_notes'), ensure_ascii=False) + '\n')

OUT.close()
print('done')
