#!/usr/bin/env python3
"""Coletor da parte Ações da aba "FIIs e ações" do Hub (roda no GitHub Actions).

Grava acoes.json ao lado do Hub com as ações negociadas:
  - Fundamentus (resultado.php): cotação, P/L, P/VP, dividend yield, EV/EBITDA, margens,
    ROE, ROIC, liquidez, patrimônio líquido, dívida líquida/patrimônio, crescimento da receita;
  - Yahoo Finance (as com liquidez): nome, dividendos de 12 meses e variação da ação em 12 meses.
Dados públicos de mercado, sem criptografia. Mantém o arquivo anterior se tiver menos de 6 horas.
Uso: python acoes_coletar.py [acoes_anterior.json]
"""
import html, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fiis_coletar import baixar, num, yahoo, BRT, coletar_noticias, noticias_velhas  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, 'acoes.json')
LIQ_MIN = 300000   # R$/dia (média de 2 meses)


def fundamentus():
    pag = baixar('https://www.fundamentus.com.br/resultado.php').decode('latin-1', 'replace')
    corpo = pag[pag.find('<tbody'):pag.find('</tbody>')]
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', corpo, re.S):
        t = [html.unescape(re.sub(r'<[^>]+>', '', td)).strip() for td in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(t) < 22 or not re.fullmatch(r'[A-Z]{4}\d{1,2}', t[0]):
            continue
        out[t[0]] = {
            't': t[0], 'preco': num(t[1]), 'pl': num(t[2]), 'pvp': num(t[3]), 'dy12': num(t[5]),
            'evebitda': num(t[11]), 'mbruta': num(t[12]), 'mliq': num(t[14]), 'roic': num(t[16]), 'roe': num(t[17]),
            'liq': num(t[18]), 'pl_patr': num(t[19]), 'divpl': num(t[20]), 'cresc5': num(t[21]),
        }
    if len(out) < 200:
        raise SystemExit('Fundamentus veio com poucas ações (%d): mantém o anterior' % len(out))
    return out


def main():
    ant = {}
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        try:
            ant = json.load(open(sys.argv[1], encoding='utf-8'))
        except Exception:  # noqa: BLE001
            ant = {}
    em = ant.get('em') or ''
    if em:
        try:
            if datetime.now(BRT) - datetime.fromisoformat(em) < timedelta(hours=6) and len(ant.get('acoes') or []) > 100:
                json.dump(ant, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
                print('acoes.json recente (%s): mantido' % em)
                if noticias_velhas(sys.argv[2] if len(sys.argv) > 2 else None):
                    coletar_noticias([x['t'] for x in ant['acoes'][:150]], os.path.join(AQUI, 'acoes_noticias.json'),
                                     sys.argv[2] if len(sys.argv) > 2 else None)
                return
        except Exception:  # noqa: BLE001
            pass
    base = {t: a for t, a in fundamentus().items() if (a.get('liq') or 0) >= LIQ_MIN and (a.get('preco') or 0) > 0}
    antigos = {a['t']: a for a in (ant.get('acoes') or [])}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, d in ex.map(yahoo, list(base)):
            if d:
                base[t].update(d)
            elif t in antigos:
                for k in ('nome', 'var12', 'spark', 'ultDiv', 'ultDivEm', 'div12', 'divs'):
                    if k in antigos[t]:
                        base[t][k] = antigos[t][k]
    for t, a in base.items():
        if not a.get('nome') and t in antigos and antigos[t].get('nome'):
            a['nome'] = antigos[t]['nome']
        p = a.get('preco')
        if p and a.get('div12') and a.get('var12') is not None:
            a['ret12'] = round(a['var12'] + a['div12'] / (p / (1 + a['var12'] / 100)) * 100, 2)
    lista = sorted(base.values(), key=lambda a: -(a.get('liq') or 0))
    out = {'em': datetime.now(BRT).isoformat(timespec='seconds'), 'fonte': 'Fundamentus e Yahoo Finance', 'acoes': lista}
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('acoes.json: %d ações, %d com dados do Yahoo' % (len(lista), sum(1 for a in lista if a.get('nome'))))
    coletar_noticias([a['t'] for a in lista[:150]], os.path.join(AQUI, 'acoes_noticias.json'),
                     sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == '__main__':
    main()
