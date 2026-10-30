#!/usr/bin/env python3
"""Coletor da seção Mercado do Hub (roda no GitHub Actions).

Grava mercado.json ao lado do Hub com:
  - juros futuros (DI1, B3): taxa atual de cada vencimento de janeiro e o histórico
    diário acumulado a cada execução (a B3 não publica a série pronta);
  - índices, dólar e ações (Yahoo Finance): série diária de 1 ano (renovada
    algumas vezes por dia) e o intradiário do dia (a cada execução);
  - Selic e IPCA (SGS do Banco Central): nível da taxa, taxa de cada mês e o
    número-índice acumulado (para comparar com os outros ativos).
São dados públicos de mercado; o arquivo não é criptografado.
Uso: python mercado_coletar.py [mercado_anterior.json]
"""
import json, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, 'mercado.json')
UA = 'Mozilla/5.0 (compatible; HubDoAssessor/1.0; +https://gustavoamorim27-svg.github.io/hub-do-assessor/)'
BRT = timezone(timedelta(hours=-3))

ATIVOS = [
    # id, nome, simbolo Yahoo, grupo, casas, prefixo
    ('ibov', 'Ibovespa', '^BVSP', 'indices', 0, ''),
    ('sp500', 'S&P 500', '^GSPC', 'indices', 0, ''),
    ('nasdaq', 'Nasdaq', '^IXIC', 'indices', 0, ''),
    ('dolar', 'Dólar', 'BRL=X', 'indices', 4, 'R$ '),
    ('brent', 'Brent', 'BZ=F', 'indices', 2, 'US$ '),
    ('ouro', 'Ouro', 'GC=F', 'indices', 2, 'US$ '),
    ('btc', 'Bitcoin', 'BTC-USD', 'indices', 0, 'US$ '),
    ('PETR4', 'Petrobras', 'PETR4.SA', 'br', 2, 'R$ '),
    ('VALE3', 'Vale', 'VALE3.SA', 'br', 2, 'R$ '),
    ('ITUB4', 'Itaú Unibanco', 'ITUB4.SA', 'br', 2, 'R$ '),
    ('BBDC4', 'Bradesco', 'BBDC4.SA', 'br', 2, 'R$ '),
    ('BBAS3', 'Banco do Brasil', 'BBAS3.SA', 'br', 2, 'R$ '),
    ('B3SA3', 'B3', 'B3SA3.SA', 'br', 2, 'R$ '),
    ('WEGE3', 'WEG', 'WEGE3.SA', 'br', 2, 'R$ '),
    ('ABEV3', 'Ambev', 'ABEV3.SA', 'br', 2, 'R$ '),
    ('AAPL', 'Apple', 'AAPL', 'us', 2, 'US$ '),
    ('MSFT', 'Microsoft', 'MSFT', 'us', 2, 'US$ '),
    ('NVDA', 'Nvidia', 'NVDA', 'us', 2, 'US$ '),
    ('AMZN', 'Amazon', 'AMZN', 'us', 2, 'US$ '),
    ('GOOGL', 'Alphabet', 'GOOGL', 'us', 2, 'US$ '),
    ('META', 'Meta', 'META', 'us', 2, 'US$ '),
    ('TSLA', 'Tesla', 'TSLA', 'us', 2, 'US$ '),
]
DI_VENCTOS = ['F27', 'F28', 'F29', 'F30', 'F31', 'F32', 'F33', 'F35']
DIARIO_HORAS = 6  # serie de 1 ano: renova a cada 6 h
MENSAL_HORAS = 20  # fechamentos mensais: uma vez por dia


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8'))


def yahoo(simbolo, rng, intervalo, ajustado=False):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(simbolo)
           + '?range=' + rng + '&interval=' + intervalo + '&includePrePost=false')
    j = get_json(url)
    res = j['chart']['result'][0]
    ts = res.get('timestamp') or []
    close = (res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
    if ajustado:
        adj = ((res.get('indicators', {}).get('adjclose') or [{}])[0].get('adjclose')) or []
        if len(adj) == len(close):
            close = [a if a is not None else c for a, c in zip(adj, close)]
    pts = [[int(t) * 1000, round(float(c), 6)] for t, c in zip(ts, close) if c is not None]
    meta = res.get('meta', {})
    return pts, meta


def coletar_ativo(a, anterior):
    aid, nome, sym, grupo, casas, prefixo = a
    ant = (anterior.get('series') or {}).get(aid) or {}
    s = {'nome': nome, 'simbolo': sym, 'grupo': grupo, 'casas': casas, 'prefixo': prefixo,
         'diario': ant.get('diario') or [], 'diarioEm': ant.get('diarioEm') or 0,
         'intradia': [], 'ultimo': ant.get('ultimo'), 'anterior': ant.get('anterior'), 'em': ant.get('em'),
         'mensal': ant.get('mensal') or [], 'mensalEm': ant.get('mensalEm') or 0}
    agora = time.time()
    try:
        if not s['diario'] or agora - s['diarioEm'] / 1000 > DIARIO_HORAS * 3600:
            pts, meta = yahoo(sym, '1y', '1d')
            if pts:
                s['diario'], s['diarioEm'] = pts, int(agora * 1000)
        if not s['mensal'] or agora - s['mensalEm'] / 1000 > MENSAL_HORAS * 3600:
            # fechamento mensal de 6 anos (ajustado por proventos) para a tabela de rentabilidade
            pm, _ = yahoo(sym, '6y', '1mo', ajustado=True)
            if pm:
                s['mensal'], s['mensalEm'] = pm, int(agora * 1000)
        pts, meta = yahoo(sym, '1d', '5m')
        s['intradia'] = pts
        if meta.get('regularMarketPrice') is not None:
            s['ultimo'] = meta['regularMarketPrice']
            s['anterior'] = meta.get('chartPreviousClose', meta.get('previousClose'))
            s['em'] = int((meta.get('regularMarketTime') or agora) * 1000)
        print(f'ok   {aid:7s} {len(s["diario"]):4d} dias  {len(pts):3d} pontos hoje  ultimo={s["ultimo"]}')
    except Exception as e:
        print(f'erro {aid:7s} {type(e).__name__}: {str(e)[:100]}', file=sys.stderr)
    return aid, s


def coletar_di(anterior):
    """Taxas do DI1 pela API publica de cotacoes da B3 (curPrc ja e a taxa % a.a.)."""
    ant = anterior.get('di') or {}
    out = {'vencimentos': {}, 'em': ant.get('em')}
    try:
        j = get_json('https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1')
        por = {x.get('symb'): x for x in j.get('Scty', [])}
        hoje = datetime.now(BRT)
        chave = hoje.strftime('%Y-%m-%d')
        util = hoje.weekday() < 5
        for v in DI_VENCTOS:
            sym = 'DI1' + v
            a = (ant.get('vencimentos') or {}).get(sym) or {}
            hist = {d: t for d, t in (a.get('historico') or [])}
            intr = a.get('intradia') or []
            x = por.get(sym)
            item = {'nome': 'DI jan/' + v[1:], 'vencimento': None, 'taxa': a.get('taxa'),
                    'ajusteAnterior': a.get('ajusteAnterior'), 'historico': [], 'intradia': []}
            if x:
                q = x.get('SctyQtn') or {}
                taxa = q.get('curPrc') or q.get('avrgPric')
                item['vencimento'] = ((x.get('asset') or {}).get('AsstSummry') or {}).get('mtrtyCode')
                item['ajusteAnterior'] = q.get('prvsDayAdjstmntPric')
                if taxa:
                    item['taxa'] = taxa
                    if util:
                        hist[chave] = taxa
                        # intradiario: so do dia corrente
                        intr = [p for p in intr if datetime.fromtimestamp(p[0] / 1000, BRT).strftime('%Y-%m-%d') == chave]
                        intr.append([int(time.time() * 1000), taxa])
                    # o ajuste do dia anterior completa o historico quando a coleta nao rodou
                    if item['ajusteAnterior']:
                        dia_ant = hoje - timedelta(days=1)
                        while dia_ant.weekday() >= 5:
                            dia_ant -= timedelta(days=1)
                        hist[dia_ant.strftime('%Y-%m-%d')] = item['ajusteAnterior']
            item['historico'] = sorted(hist.items())[-400:]
            item['intradia'] = intr[-200:]
            out['vencimentos'][sym] = item
        out['em'] = int(time.time() * 1000)
        print('ok   DI1', {k: v['taxa'] for k, v in out['vencimentos'].items()})
    except Exception as e:
        print(f'erro DI1 {type(e).__name__}: {str(e)[:120]}', file=sys.stderr)
        if ant:
            out = ant
    return out


BCB_HORAS = 6  # Selic e IPCA mudam pouco: renova a cada 6 h


def sgs(codigo, anos=6):
    """Serie do SGS do Banco Central: [[ts_ms, valor], ...] (data ao meio-dia, horario de Brasilia)."""
    hoje = datetime.now(BRT)
    ini = (hoje - timedelta(days=int(anos * 365.25) + 40)).strftime('%d/%m/%Y')
    url = ('https://api.bcb.gov.br/dados/serie/bcdata.sgs.' + str(codigo) + '/dados?formato=json'
           + '&dataInicial=' + urllib.parse.quote(ini, safe='') + '&dataFinal=' + urllib.parse.quote(hoje.strftime('%d/%m/%Y'), safe=''))
    j = get_json(url)
    out = []
    for x in j:
        d = datetime.strptime(x['data'], '%d/%m/%Y').replace(hour=12, tzinfo=BRT)
        out.append([int(d.timestamp() * 1000), float(str(x['valor']).replace(',', '.'))])
    out.sort()
    return out


def fim_do_mes(ts):
    d = datetime.fromtimestamp(ts / 1000, BRT)
    prox = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return int((prox - timedelta(days=1)).timestamp() * 1000)


def coletar_bcb(anterior):
    """Selic (meta do Copom) e IPCA pelo SGS do Banco Central.
    diario  = nivel da taxa para o grafico (Selic meta % a.a. por dia util; IPCA 12 meses por mes)
    mensal  = taxa de cada mes (% a.m.) para a tabela de rentabilidade
    indice  = numero-indice acumulado (Selic diaria / IPCA mensal) para comparar com outros ativos."""
    out = {}
    agora = time.time()
    defs = [
        ('selic', {'nome': 'Selic', 'simbolo': 'Meta Copom', 'grupo': 'indices', 'tipo': 'taxa', 'casas': 2,
                   'prefixo': '', 'sufixo': '% a.a.', 'fonte': 'Banco Central (SGS 432, 11 e 4390)'}),
        ('ipca', {'nome': 'IPCA', 'simbolo': '12 meses · IBGE', 'grupo': 'indices', 'tipo': 'taxa', 'casas': 2,
                  'prefixo': '', 'sufixo': '% em 12 meses', 'fonte': 'IBGE via Banco Central (SGS 433 e 13522)'}),
    ]
    for aid, base in defs:
        ant = (anterior.get('series') or {}).get(aid) or {}
        s = dict(base)
        for c in ('diario', 'mensal', 'indice', 'ultimo', 'anterior', 'em', 'mudouEm', 'diarioEm'):
            s[c] = ant.get(c)
        if s['diario'] and agora - (s['diarioEm'] or 0) / 1000 < BCB_HORAS * 3600:
            out[aid] = s
            print(f'ok   {aid:7s} (mantido, coletado ha menos de {BCB_HORAS} h)')
            continue
        try:
            if aid == 'selic':
                meta = [p for p in sgs(432) if datetime.fromtimestamp(p[0] / 1000, BRT).weekday() < 5]
                diaria = sgs(11)
                mensal = sgs(4390)
                idx, v = [], 1.0
                for ts, r in diaria:
                    v *= 1 + r / 100
                    idx.append([ts, float('%.10g' % v)])
                s['indice'] = idx
                s['diario'] = meta
                s['mensal'] = mensal
            else:
                mensal = sgs(433)
                doze = sgs(13522)
                idx, v = [], 1.0
                for ts, r in mensal:
                    v *= 1 + r / 100
                    idx.append([fim_do_mes(ts), float('%.10g' % v)])
                s['indice'] = idx
                s['diario'] = doze
                s['mensal'] = mensal
            if s['diario']:
                s['ultimo'] = s['diario'][-1][1]
                s['em'] = s['diario'][-1][0]
                ant_v = None
                for ts, val in reversed(s['diario']):
                    if val != s['ultimo']:
                        ant_v = val
                        break
                    s['mudouEm'] = ts
                s['anterior'] = ant_v
                s['diarioEm'] = int(agora * 1000)
            print(f'ok   {aid:7s} {len(s["diario"] or []):4d} pontos  ultimo={s["ultimo"]}  mensal={len(s["mensal"] or [])}')
        except Exception as e:
            print(f'erro {aid:7s} {type(e).__name__}: {str(e)[:100]}', file=sys.stderr)
        if s.get('diario'):
            out[aid] = s
    return out


def main():
    anterior = {}
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        try:
            anterior = json.load(open(sys.argv[1], encoding='utf-8'))
        except Exception:
            anterior = {}
    with ThreadPoolExecutor(4) as ex:
        series = dict(ex.map(lambda a: coletar_ativo(a, anterior), ATIVOS))
    # Selic e IPCA entram no grupo de indices logo depois do Ibovespa
    bcb = coletar_bcb(anterior)
    if bcb:
        ordem = {}
        for k, v in series.items():
            ordem[k] = v
            if k == 'ibov':
                ordem.update(bcb)
        series = ordem
    di = coletar_di(anterior)
    com_dados = sum(1 for s in series.values() if s['diario'])
    if not com_dados and not di.get('vencimentos'):
        sys.exit('nenhum dado de mercado — mantenho o arquivo anterior')
    dados = {'geradoEm': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'series': series, 'di': di}
    json.dump(dados, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('gravado', SAIDA, os.path.getsize(SAIDA), 'bytes;', com_dados, 'séries com histórico')


if __name__ == '__main__':
    main()
