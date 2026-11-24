#!/usr/bin/env python3
"""Coletor da aba Fundos imobiliários do Hub (roda no GitHub Actions).

Grava fiis.json ao lado do Hub com todos os FIIs negociados:
  - Fundamentus (fii_resultado): segmento, cotação, dividend yield 12M, P/VP, valor de
    mercado, liquidez diária, vacância;
  - Yahoo Finance (para os FIIs com liquidez): nome, último rendimento (para o DY do mês),
    rendimentos dos últimos 12 meses e a variação da cota em 12 meses.
São dados públicos de mercado; o arquivo não é criptografado.
Uso: python fiis_coletar.py [fiis_anterior.json]
Se o arquivo anterior tiver menos de 6 horas, mantém (não precisa coletar a cada publicação).
"""
import html, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, 'fiis.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
BRT = timezone(timedelta(hours=-3))
LIQ_MIN = 30000      # R$/dia: abaixo disso não vale a consulta no Yahoo (fundos sem negócio)


def baixar(url, tentativas=3):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            erro = e
            time.sleep(1.5 * (i + 1))
    raise erro


def num(t):
    t = (t or '').strip().replace('%', '').replace('.', '').replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def fundamentus():
    pag = baixar('https://www.fundamentus.com.br/fii_resultado.php').decode('latin-1', 'replace')
    corpo = pag[pag.find('<tbody'):pag.find('</tbody>')]
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', corpo, re.S):
        tds = [html.unescape(re.sub(r'<[^>]+>', '', td)).strip() for td in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(tds) < 13 or not re.fullmatch(r'[A-Z]{4}1[1-4]', tds[0]):
            continue
        out[tds[0]] = {
            't': tds[0], 'seg': tds[1] or 'Outros', 'preco': num(tds[2]), 'ffo': num(tds[3]),
            'dy12': num(tds[4]), 'pvp': num(tds[5]), 'vm': num(tds[6]), 'liq': num(tds[7]),
            'imoveis': num(tds[8]), 'cap': num(tds[11]), 'vac': num(tds[12]),
        }
    if len(out) < 100:
        raise SystemExit('Fundamentus veio com poucos FIIs (%d): mantém o anterior' % len(out))
    return out


def yahoo(t):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(t + '.SA')
           + '?range=1y&interval=1d&events=div&includePrePost=false')
    try:
        j = json.loads(baixar(url, 2))
        res = j['chart']['result'][0]
    except Exception:  # noqa: BLE001
        return t, None
    meta = res.get('meta', {})
    close = [c for c in ((res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []) if c]
    divs = sorted(((int(k), v.get('amount')) for k, v in ((res.get('events') or {}).get('dividends') or {}).items() if v.get('amount')))
    d = {'nome': (meta.get('longName') or meta.get('shortName') or '').strip()}
    if len(close) > 20:
        d['var12'] = round((close[-1] / close[0] - 1) * 100, 2)
        d['spark'] = [round(c, 2) for c in close[::max(1, len(close) // 40)]][-40:]
    if divs:
        d['ultDiv'] = round(divs[-1][1], 4)
        d['ultDivEm'] = datetime.fromtimestamp(divs[-1][0], BRT).strftime('%Y-%m-%d')
        d['div12'] = round(sum(a for _, a in divs), 4)
        d['divs'] = [[datetime.fromtimestamp(k, BRT).strftime('%Y-%m-%d'), round(a, 4)] for k, a in divs[-12:]]
    return t, d


NEWS_TOP = 200   # FIIs mais negociados com notícias pré-coletadas (o Hub busca as dos outros na hora)


def noticias_de(t):
    """Até 8 manchetes recentes do Google Notícias para o ticker."""
    import xml.etree.ElementTree as ET
    url = ('https://news.google.com/rss/search?q=' + urllib.parse.quote('"%s" when:120d' % t)
           + '&hl=pt-BR&gl=BR&ceid=BR:pt-419')
    try:
        raiz = ET.fromstring(baixar(url, 2))
    except Exception:  # noqa: BLE001
        return t, None
    itens = []
    for it in raiz.iter('item'):
        tit = (it.findtext('title') or '').strip()
        fonte = (it.findtext('source') or '').strip()
        if fonte and tit.endswith(' - ' + fonte):
            tit = tit[: -len(fonte) - 3]
        em = it.findtext('pubDate') or ''
        try:
            em = datetime.strptime(em[:25].strip(), '%a, %d %b %Y %H:%M:%S').strftime('%Y-%m-%d')
        except ValueError:
            em = ''
        itens.append({'tit': tit, 'fonte': fonte, 'link': it.findtext('link') or '', 'em': em})
    itens.sort(key=lambda x: x['em'], reverse=True)
    return t, itens[:8]


def noticias_velhas(arq):
    try:
        em = json.load(open(arq, encoding='utf-8')).get('em') if arq and os.path.exists(arq) else ''
        return not em or datetime.now(BRT) - datetime.fromisoformat(em) > timedelta(hours=6)
    except Exception:  # noqa: BLE001
        return True


def coletar_noticias(tickers, saida, anterior):
    """Grava {ticker: [manchetes]}; o que falhar fica com as do arquivo anterior."""
    ant = {}
    try:
        ant = json.load(open(anterior, encoding='utf-8')).get('n', {}) if anterior and os.path.exists(anterior) else {}
    except Exception:  # noqa: BLE001
        ant = {}
    out = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for t, itens in ex.map(noticias_de, tickers):
            if itens is not None:
                out[t] = itens
            elif t in ant:
                out[t] = ant[t]
    json.dump({'em': datetime.now(BRT).isoformat(timespec='seconds'), 'n': out}, open(saida, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print('%s: notícias de %d ativos' % (os.path.basename(saida), len(out)))


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
            idade = datetime.now(BRT) - datetime.fromisoformat(em)
            if idade < timedelta(hours=6) and len(ant.get('fiis') or []) > 100:
                json.dump(ant, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
                print('fiis.json recente (%s): mantido' % em)
                if noticias_velhas(sys.argv[2] if len(sys.argv) > 2 else None):
                    coletar_noticias([x['t'] for x in ant['fiis'][:NEWS_TOP]], os.path.join(AQUI, 'fiis_noticias.json'),
                                     sys.argv[2] if len(sys.argv) > 2 else None)
                return
        except Exception:  # noqa: BLE001
            pass
    base = fundamentus()
    antigos = {f['t']: f for f in (ant.get('fiis') or [])}
    alvos = [t for t, f in base.items() if (f.get('liq') or 0) >= LIQ_MIN]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, d in ex.map(yahoo, alvos):
            if d:
                base[t].update(d)
            elif t in antigos:  # Yahoo falhou para este: aproveita o que já tinha
                for k in ('nome', 'var12', 'spark', 'ultDiv', 'ultDivEm', 'div12', 'divs'):
                    if k in antigos[t]:
                        base[t][k] = antigos[t][k]
    for t, f in base.items():
        if not f.get('nome') and t in antigos and antigos[t].get('nome'):
            f['nome'] = antigos[t]['nome']
        p = f.get('preco')
        if p and f.get('ultDiv'):
            f['dyMes'] = round(f['ultDiv'] / p * 100, 2)
        if p and f.get('div12') and f.get('var12') is not None:
            f['ret12'] = round(f['var12'] + f['div12'] / (p / (1 + f['var12'] / 100)) * 100, 2)
    lista = sorted(base.values(), key=lambda f: -(f.get('liq') or 0))
    out = {'em': datetime.now(BRT).isoformat(timespec='seconds'), 'fonte': 'Fundamentus e Yahoo Finance', 'fiis': lista}
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('fiis.json: %d FIIs, %d com dados do Yahoo' % (len(lista), sum(1 for f in lista if f.get('nome'))))
    coletar_noticias([f['t'] for f in lista[:NEWS_TOP]], os.path.join(AQUI, 'fiis_noticias.json'),
                     sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == '__main__':
    main()
