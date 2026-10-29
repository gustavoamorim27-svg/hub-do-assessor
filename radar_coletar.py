#!/usr/bin/env python3
"""Coletor do Radar de mercado (roda no GitHub Actions).

Lê os feeds RSS do Radar (manchetes, Morning Call da XP, podcast e relatórios
da XP), monta um JSON no mesmo formato que o rss2json devolvia e grava
radar.enc ao lado do Hub. Assim o Hub lê as notícias do próprio endereço
(github.io), que passa pela rede da Rico, sem depender de proxy de terceiros.

radar.enc = {"v":1, "geradoEm":..., "k":RSA-OAEP-SHA256(chave AES), "iv":..., "ct":AES-256-GCM(gzip(json))}
Só a chave pública (radar_chave.pem) fica no repositório; a privada vai dentro do hub.enc.
"""
import base64, gzip, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, 'radar.enc')

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/129.0 Safari/537.36')


def gnews(q, br=True):
    base = 'https://news.google.com/rss/search?q=' + urllib.parse.quote(q)
    return base + ('&hl=pt-BR&gl=BR&ceid=BR:pt-419' if br else '&hl=en-US&gl=US&ceid=US:en')


# url do feed (a mesma que o Hub pede) -> (limite de itens, reserva no Google Notícias, guardar conteúdo?)
FEEDS = {
    'https://www.infomoney.com.br/mercados/feed/': (25, gnews('site:infomoney.com.br mercados when:2d'), False),
    'https://www.infomoney.com.br/economia/feed/': (25, gnews('site:infomoney.com.br economia when:2d'), False),
    'https://www.moneytimes.com.br/feed/': (25, gnews('site:moneytimes.com.br when:2d'), False),
    'https://exame.com/invest/feed/': (25, gnews('site:exame.com invest when:2d'), False),
    'https://www.bloomberglinea.com.br/arc/outboundfeeds/rss/?outputType=xml': (25, gnews('site:bloomberglinea.com.br when:2d'), False),
    'https://g1.globo.com/rss/g1/economia/': (25, gnews('site:g1.globo.com economia when:2d'), False),
    'https://www.cnbc.com/id/10000664/device/rss/rss.html': (25, gnews('site:cnbc.com markets when:2d', False), False),
    'https://feeds.a.dj.com/rss/RSSMarketsMain.xml': (25, gnews('site:wsj.com markets when:2d', False), False),
    'https://feeds.content.dowjones.io/public/rss/mw_topstories': (25, gnews('site:marketwatch.com when:2d', False), False),
    'https://finance.yahoo.com/news/rssindex': (25, gnews('site:finance.yahoo.com when:2d', False), False),
    # daily de referência
    'https://conteudos.xpi.com.br/morning-call/feed/': (10, gnews('site:conteudos.xpi.com.br/morning-call when:3d'), True),
    'https://anchor.fm/s/104cb6d1c/podcast/rss': (3, None, False),
    # Raio-XP (card da Visão geral)
    'https://conteudos.xpi.com.br/acoes/relatorios/feed/': (30, None, False),
    'https://conteudos.xpi.com.br/acoes/relatorios/feed/?paged=2': (30, None, False),
}

NS = {
    'content': 'http://purl.org/rss/1.0/modules/content/',
    'media': 'http://search.yahoo.com/mrss/',
    'atom': 'http://www.w3.org/2005/Atom',
    'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
}


def baixar(url, tentativas=2):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8',
                'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except Exception as e:
            print('  falhou', url, '->', type(e).__name__, str(e)[:120], file=sys.stderr)
            time.sleep(2)
    return None


def txt(el):
    return (el.text or '').strip() if el is not None else ''


def data_utc(s):
    s = (s or '').strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace('Z', '+00:00'))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def corta(s, n):
    s = s or ''
    return s if len(s) <= n else s[:n]


def ler_feed(xml, limite, conteudo):
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        # alguns feeds trazem lixo antes do <?xml
        i = xml.find(b'<')
        raiz = ET.fromstring(xml[i:])
    itens = []
    canal = raiz.find('channel')
    if canal is not None:
        brutos = canal.findall('item')
        titulo_feed = txt(canal.find('title'))
    else:  # Atom
        brutos = raiz.findall('atom:entry', NS)
        titulo_feed = txt(raiz.find('atom:title', NS))
    for it in brutos:
        if canal is not None:
            titulo = txt(it.find('title'))
            link = txt(it.find('link'))
            guid = txt(it.find('guid'))
            pub = data_utc(txt(it.find('pubDate')) or txt(it.find('{http://purl.org/dc/elements/1.1/}date')))
            desc = txt(it.find('description'))
            cont = txt(it.find('content:encoded', NS))
            enc = it.find('enclosure')
            enclosure = {'link': enc.get('url', ''), 'type': enc.get('type', '')} if enc is not None else {}
        else:
            titulo = txt(it.find('atom:title', NS))
            le = it.find('atom:link', NS)
            link = le.get('href', '') if le is not None else ''
            guid = txt(it.find('atom:id', NS))
            pub = data_utc(txt(it.find('atom:published', NS)) or txt(it.find('atom:updated', NS)))
            desc = txt(it.find('atom:summary', NS))
            cont = txt(it.find('atom:content', NS))
            enclosure = {}
        thumb = ''
        for tag in ('media:thumbnail', 'media:content'):
            m = it.find(tag, NS)
            if m is not None and m.get('url') and (tag == 'media:thumbnail' or 'image' in (m.get('type') or 'image') or m.get('medium') == 'image'):
                thumb = m.get('url')
                break
        if not thumb and enclosure.get('type', '').startswith('image'):
            thumb = enclosure.get('link', '')
        if not titulo or not link or pub is None:
            continue
        itens.append({
            'title': titulo,
            'pubDate': pub.strftime('%Y-%m-%d %H:%M:%S'),
            'link': link,
            'guid': guid or link,
            'thumbnail': thumb,
            'description': corta(desc, 1500 if conteudo else 700),
            'content': corta(cont, 20000) if conteudo else '',
            'enclosure': enclosure,
        })
    # mais recente primeiro (o Google Notícias ordena por relevância)
    itens.sort(key=lambda x: x['pubDate'], reverse=True)
    return {'feed': {'title': titulo_feed}, 'items': itens[:limite]}


def recente(feed, horas=72):
    agora = time.time()
    for it in feed.get('items', []):
        try:
            ts = datetime.strptime(it['pubDate'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue
        if agora - ts < horas * 3600:
            return True
    return False


def coletar_um(url, cfg):
    limite, reserva, conteudo = cfg
    feed = None
    xml = baixar(url)
    if xml:
        try:
            feed = ler_feed(xml, limite, conteudo)
        except Exception as e:
            print('  não li', url, e, file=sys.stderr)
    origem = 'direto'
    if (not feed or not recente(feed)) and reserva:
        xml = baixar(reserva)
        if xml:
            try:
                f2 = ler_feed(xml, limite, conteudo)
                if f2['items']:
                    # o Google Notícias põe " - Fonte" no fim do título
                    for it in f2['items']:
                        it['title'] = re.sub(r'\s+-\s+[^-]{2,40}$', '', it['title'])
                        it['description'] = ''
                    feed, origem = f2, 'google'
            except Exception as e:
                print('  não li a reserva de', url, e, file=sys.stderr)
    n = len(feed['items']) if feed else 0
    print(f'{n:3d} itens  [{origem}]  {url}')
    return url, (dict(feed, origem=origem) if feed and n else None)


def criptografar(dados):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pub = serialization.load_pem_public_key(open(os.path.join(AQUI, 'radar_chave.pem'), 'rb').read())
    chave = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ct = AESGCM(chave).encrypt(iv, gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9), None)
    k = pub.encrypt(chave, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b = lambda x: base64.b64encode(x).decode()
    return {'v': 1, 'geradoEm': dados['geradoEm'], 'k': b(k), 'iv': b(iv), 'ct': b(ct)}


def main():
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(lambda kv: coletar_um(*kv), FEEDS.items()))
    feeds = {u: f for u, f in res.items() if f}
    manchetes = sum(1 for u in feeds if 'xpi.com.br' not in u and 'anchor.fm' not in u)
    if not feeds or manchetes < 2:
        sys.exit('coleta fraca demais (%d feeds) — mantenho o radar anterior' % len(feeds))
    dados = {'geradoEm': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'feeds': feeds}
    json.dump(criptografar(dados), open(SAIDA, 'w'))
    print('gravado', SAIDA, os.path.getsize(SAIDA), 'bytes,', len(feeds), 'feeds')


if __name__ == '__main__':
    main()
