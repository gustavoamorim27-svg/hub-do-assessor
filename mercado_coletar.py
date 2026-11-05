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
import json, os, re, sys, time, urllib.parse, urllib.request
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
    ('btc', 'Bitcoin', 'BTC-USD', 'indices', 0, 'US$ '),
    # commodities (secao propria)
    ('brent', 'Petróleo Brent', 'BZ=F', 'commod', 2, 'US$ '),
    ('wti', 'Petróleo WTI', 'CL=F', 'commod', 2, 'US$ '),
    ('ouro', 'Ouro', 'GC=F', 'commod', 2, 'US$ '),
    ('prata', 'Prata', 'SI=F', 'commod', 2, 'US$ '),
    ('cobre', 'Cobre', 'HG=F', 'commod', 3, 'US$ '),
    ('soja', 'Soja', 'ZS=F', 'commod', 2, 'US¢ '),
    ('cafe', 'Café', 'KC=F', 'commod', 2, 'US¢ '),
    ('PETR4', 'Petrobras', 'PETR4.SA', 'br', 2, 'R$ '),
    ('VALE3', 'Vale', 'VALE3.SA', 'br', 2, 'R$ '),
    ('ITUB4', 'Itaú Unibanco', 'ITUB4.SA', 'br', 2, 'R$ '),
    ('BBDC4', 'Bradesco', 'BBDC4.SA', 'br', 2, 'R$ '),
    ('BBAS3', 'Banco do Brasil', 'BBAS3.SA', 'br', 2, 'R$ '),
    ('B3SA3', 'B3', 'B3SA3.SA', 'br', 2, 'R$ '),
    ('WEGE3', 'WEG', 'WEGE3.SA', 'br', 2, 'R$ '),
    ('ABEV3', 'Ambev', 'ABEV3.SA', 'br', 2, 'R$ '),
    ('ITSA4', 'Itaúsa', 'ITSA4.SA', 'br', 2, 'R$ '),
    ('BPAC11', 'BTG Pactual', 'BPAC11.SA', 'br', 2, 'R$ '),
    ('PRIO3', 'PRIO', 'PRIO3.SA', 'br', 2, 'R$ '),
    ('SUZB3', 'Suzano', 'SUZB3.SA', 'br', 2, 'R$ '),
    ('SBSP3', 'Sabesp', 'SBSP3.SA', 'br', 2, 'R$ '),
    ('EQTL3', 'Equatorial', 'EQTL3.SA', 'br', 2, 'R$ '),
    ('RDOR3', 'Rede D\'Or', 'RDOR3.SA', 'br', 2, 'R$ '),
    ('RENT3', 'Localiza', 'RENT3.SA', 'br', 2, 'R$ '),
    ('GGBR4', 'Gerdau', 'GGBR4.SA', 'br', 2, 'R$ '),
    ('RADL3', 'Raia Drogasil', 'RADL3.SA', 'br', 2, 'R$ '),
    ('AAPL', 'Apple', 'AAPL', 'us', 2, 'US$ '),
    ('MSFT', 'Microsoft', 'MSFT', 'us', 2, 'US$ '),
    ('NVDA', 'Nvidia', 'NVDA', 'us', 2, 'US$ '),
    ('AMZN', 'Amazon', 'AMZN', 'us', 2, 'US$ '),
    ('GOOGL', 'Alphabet', 'GOOGL', 'us', 2, 'US$ '),
    ('META', 'Meta', 'META', 'us', 2, 'US$ '),
    ('TSLA', 'Tesla', 'TSLA', 'us', 2, 'US$ '),
    ('AVGO', 'Broadcom', 'AVGO', 'us', 2, 'US$ '),
    ('BRK-B', 'Berkshire Hathaway', 'BRK-B', 'us', 2, 'US$ '),
    ('JPM', 'JPMorgan', 'JPM', 'us', 2, 'US$ '),
    ('LLY', 'Eli Lilly', 'LLY', 'us', 2, 'US$ '),
    ('V', 'Visa', 'V', 'us', 2, 'US$ '),
    ('NFLX', 'Netflix', 'NFLX', 'us', 2, 'US$ '),
    ('AMD', 'AMD', 'AMD', 'us', 2, 'US$ '),
    ('PLTR', 'Palantir', 'PLTR', 'us', 2, 'US$ '),
]
# a lista do Hub mostra so jan/30 e jan/31; os outros vencimentos seguem na
# coleta porque desenham a curva de juros
DI_VENCTOS = ['F27', 'F28', 'F29', 'F30', 'F31', 'F32', 'F33', 'F35']
DIARIO_HORAS = 6  # serie de 1 ano: renova a cada 6 h
# Ativos que o Gustavo acrescentou na lista dos Graficos do Hub (busca). Ficam num
# documento publico do Firestore do rico-hub; cripto nao entra aqui (vem do CoinGecko
# direto no navegador).
LISTA_DOC = ('https://firestore.googleapis.com/v1/projects/rico-hub/databases/(default)/documents/'
             'ricoPipeline/v3-mercado-lista')
MAX_EXTRAS = 60
MENSAL_HORAS = 20  # fechamentos mensais: uma vez por dia

# historico.json: fechamentos (1 ano diario + 6 anos mensal) de todo o catalogo do Hub
# (acoes, FIIs, ETFs e BDRs que nao estao na lista dos Graficos), para o mini grafico
# do Montar a carteira e para um ativo recem-acrescentado nos Graficos. Renova um lote
# por execucao (os mais antigos primeiro), sem pesar na coleta principal.
HIST_SAIDA = os.path.join(AQUI, 'historico.json')
HIST_ATIVOS = os.path.join(AQUI, 'historico_ativos.json')
HIST_URL = 'https://gustavoamorim27-svg.github.io/hub-do-assessor/historico.json'
HIST_HORAS = 20
HIST_LOTE = 45
HIST_LOTE_INICIAL = 140  # enquanto o arquivo ainda esta se formando
# velas (abertura, maxima, minima, fechamento) do mesmo catalogo, em lotes por inicial do
# ticker (hv/A.json, hv/B.json...): o site so baixa o lote quando o grafico em velas e aberto
HV_DIR = os.path.join(AQUI, 'hv')
# maximo.json: fechamentos e velas mensais de todo o historico (periodo "Max") dos ativos da
# lista dos Graficos; o site so baixa quando o periodo Max e escolhido
MAX_SAIDA = os.path.join(AQUI, 'maximo.json')
MAX_URL = 'https://gustavoamorim27-svg.github.io/hub-do-assessor/maximo.json'
MAX_ANT, MAXIMO = {}, {}
MESES_6A = 73
HV_URL = 'https://gustavoamorim27-svg.github.io/hub-do-assessor/hv/'
DIA0 = 18262  # 01/01/2020 em dias desde 1970


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8'))


def yahoo(simbolo, rng, intervalo, ajustado=False):
    pts, meta, _ = yahoo_velas(simbolo, rng, intervalo, ajustado)
    return pts, meta


def _r(v, casas):
    return round(float(v), casas)


def yahoo_velas(simbolo, rng, intervalo, ajustado=False, casas=4):
    """Fechamentos [[ts, c]], meta e velas [[ts, abertura, maxima, minima, fechamento]] (sem ajuste)."""
    # 'max' vai por datas (desde 1900): com range=max o Yahoo troca o mensal por trimestral
    # nos ativos de historico longo (S&P 500, Dow...)
    periodo = ('period1=-2208994789&period2=' + str(int(time.time()))) if rng == 'max' else ('range=' + rng)
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(simbolo)
           + '?' + periodo + '&interval=' + intervalo + '&includePrePost=false')
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
    q = (res.get('indicators', {}).get('quote') or [{}])[0]
    o, h, l, c = q.get('open') or [], q.get('high') or [], q.get('low') or [], q.get('close') or []
    velas = []
    for i, t in enumerate(ts):
        try:
            if None in (o[i], h[i], l[i], c[i]) or min(o[i], h[i], l[i], c[i]) <= 0:
                continue  # o Yahoo manda a vela do dia ainda zerada antes da abertura
            velas.append([int(t) * 1000, _r(o[i], casas), _r(h[i], casas), _r(l[i], casas), _r(c[i], casas)])
        except IndexError:
            break
    return pts, meta, velas


def extras():
    """[(id, nome, simbolo Yahoo, grupo, casas, prefixo), ...] acrescentados no Hub."""
    try:
        j = get_json(LISTA_DOC)
        d = json.loads(j['fields']['envelope']['stringValue'])
    except Exception as e:
        print('lista do Hub indisponível:', type(e).__name__, str(e)[:80])
        return []
    ja = {a[0] for a in ATIVOS}
    out = []
    for x in d.get('extras') or []:
        if not isinstance(x, dict) or x.get('fonte') == 'cg':
            continue
        aid, sym = str(x.get('id') or '').strip(), str(x.get('sym') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9.\-]{1,20}', aid) or not re.fullmatch(r'[A-Za-z0-9.\-^=]{1,20}', sym) or aid in ja:
            continue
        grupo = x.get('grupo') if x.get('grupo') in ('br', 'us', 'indices', 'commod') else 'br'
        try:
            casas = max(0, min(6, int(x.get('casas', 2))))
        except Exception:
            casas = 2
        prefixo = str(x.get('prefixo') if x.get('prefixo') is not None else ('R$ ' if grupo == 'br' else 'US$ '))[:5]
        out.append((aid, str(x.get('nome') or aid)[:60], sym, grupo, casas, prefixo))
        ja.add(aid)
        if len(out) >= MAX_EXTRAS:
            break
    print('extras do Hub:', [a[0] for a in out])
    return out


def coletar_ativo(a, anterior):
    aid, nome, sym, grupo, casas, prefixo = a
    ant = (anterior.get('series') or {}).get(aid) or {}
    s = {'nome': nome, 'simbolo': sym, 'grupo': grupo, 'casas': casas, 'prefixo': prefixo,
         'diario': ant.get('diario') or [], 'diarioEm': ant.get('diarioEm') or 0,
         'intradia': [], 'ultimo': ant.get('ultimo'), 'anterior': ant.get('anterior'), 'em': ant.get('em'),
         'mensal': ant.get('mensal') or [], 'mensalEm': ant.get('mensalEm') or 0,
         'velas': ant.get('velas') or [], 'velasM': ant.get('velasM') or [], 'velasI': []}
    cv = min(6, casas + 2)  # casas das velas
    agora = time.time()
    try:
        if not s['diario'] or not s['velas'] or agora - s['diarioEm'] / 1000 > DIARIO_HORAS * 3600:
            pts, meta, velas = yahoo_velas(sym, '1y', '1d', casas=cv)
            if pts:
                s['diario'], s['diarioEm'], s['velas'] = pts, int(agora * 1000), velas
        if (not s['mensal'] or not s['velasM'] or aid not in MAX_ANT or not _mensal_ok(s['mensal'])
                or agora - s['mensalEm'] / 1000 > MENSAL_HORAS * 3600):
            # fechamento mensal de 6 anos (ajustado por proventos) para a tabela de rentabilidade e o
            # grafico de 5 anos; as velas mensais (sem ajuste) desenham o 5A em velas
            pm, _, vm = yahoo_velas(sym, '6y', '1mo', ajustado=True, casas=cv)
            if pm:
                s['mensal'], s['mensalEm'], s['velasM'] = pm, int(agora * 1000), vm
            # todo o historico mensal, para o periodo Max (vai para o maximo.json)
            try:
                px, _, vx = yahoo_velas(sym, 'max', '1mo', ajustado=True, casas=cv)
                if px:
                    MAXIMO[aid] = {'mx': [[_dia(p[0]), p[1]] for p in px], 'vx': [[_dia(k[0])] + k[1:] for k in vx]}
            except Exception as e:
                print(f'max  {aid:7s} {type(e).__name__}: {str(e)[:80]}', file=sys.stderr)
        pts, meta, vi = yahoo_velas(sym, '1d', '5m', casas=cv)
        s['intradia'] = pts
        s['velasI'] = vi
        if meta.get('regularMarketPrice') is not None:
            s['ultimo'] = meta['regularMarketPrice']
            s['anterior'] = meta.get('chartPreviousClose', meta.get('previousClose'))
            s['em'] = int((meta.get('regularMarketTime') or agora) * 1000)
        print(f'ok   {aid:7s} {len(s["diario"]):4d} dias  {len(pts):3d} pontos hoje  ultimo={s["ultimo"]}')
    except Exception as e:
        print(f'erro {aid:7s} {type(e).__name__}: {str(e)[:100]}', file=sys.stderr)
    return aid, s


def _mensal_ok(pts):
    """Fechamentos mensais de verdade (e nao trimestrais): intervalo mediano ate 40 dias."""
    if not pts or len(pts) < 3:
        return bool(pts)
    gaps = sorted(pts[i][0] - pts[i - 1][0] for i in range(1, len(pts)))
    return gaps[len(gaps) // 2] <= 40 * 86400000


def _dia(ts_ms):
    return int(round(ts_ms / 86400000)) - DIA0


def coletar_historico(ja):
    """Atualiza historico.json; grava a copia anterior logo de cara para o site nunca ficar sem ele."""
    ant = {}
    try:
        req = urllib.request.Request(HIST_URL + '?t=' + str(int(time.time())), headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            ant = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print('historico anterior indisponivel:', type(e).__name__, str(e)[:80])
    s_ant = ant.get('s') if isinstance(ant.get('s'), dict) else {}
    if s_ant:
        json.dump(ant, open(HIST_SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    try:
        universo = json.load(open(HIST_ATIVOS, encoding='utf-8'))
    except Exception as e:
        print('lista do historico indisponivel:', e)
        return
    alvo = [a for a in universo if a[0] not in ja]
    # velas da execucao anterior (o site e montado do zero a cada vez): baixa os lotes e ja
    # regrava, para nada sumir se a coleta parar no meio
    v_ant = {}
    os.makedirs(HV_DIR, exist_ok=True)
    for L in sorted({_hv_lote(a[0]) for a in alvo}):
        try:
            req = urllib.request.Request(HV_URL + L + '.json?t=' + str(int(time.time())), headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode('utf-8'))
            if isinstance(j, dict):
                v_ant.update({k: v for k, v in j.items() if isinstance(v, dict)})
                json.dump(j, open(os.path.join(HV_DIR, L + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        except Exception:
            pass
    agora = time.time()
    sem_velas = lambda a: a[0] not in v_ant
    velhos = sorted([a for a in alvo if sem_velas(a) or agora - (s_ant.get(a[0]) or {}).get('e', 0) / 1000 > HIST_HORAS * 3600],
                    key=lambda a: (0 if sem_velas(a) else 1, (s_ant.get(a[0]) or {}).get('e', 0)))
    faltam = sum(1 for a in alvo if a[0] not in s_ant or sem_velas(a))
    lote = velhos[:HIST_LOTE_INICIAL if faltam > 40 else HIST_LOTE]

    def um(a):
        aid, nome, grupo, sym, casas, prefixo = a
        try:
            c = min(6, int(casas) + 2)
            pts, meta, vd = yahoo_velas(sym, '1y', '1d', casas=c)
            pm, _, vm = yahoo_velas(sym, 'max', '1mo', ajustado=True, casas=c)
            if not pts:
                return aid, None
            if not _mensal_ok(pm):  # o Yahoo mandou trimestral: o 6 anos vem a parte
                p6, _, v6 = yahoo_velas(sym, '6y', '1mo', ajustado=True, casas=c)
            else:
                p6, v6 = pm[-MESES_6A:], vm[-MESES_6A:]
            ult = meta.get('regularMarketPrice')
            fech = [p[1] for p in pts]
            velas[aid] = {'v': [[_dia(k[0])] + k[1:] for k in vd], 'vx': [[_dia(k[0])] + k[1:] for k in (vm if _mensal_ok(pm) else v6)],
                          'mx': [[_dia(p[0]), round(p[1], c)] for p in pm], 'e': int(agora * 1000)}
            pm = p6
            return aid, {'n': nome, 'g': grupo, 'c': casas, 'p': prefixo,
                         'd': [[_dia(p[0]), round(p[1], c)] for p in pts],
                         'm': [[_dia(p[0]), round(p[1], c)] for p in pm],
                         'u': ult if ult is not None else fech[-1],
                         'a': fech[-2] if len(fech) > 1 else None,
                         't': int((meta.get('regularMarketTime') or agora) * 1000), 'e': int(agora * 1000)}
        except Exception as e:
            print(f'hist {aid:7s} {type(e).__name__}: {str(e)[:80]}', file=sys.stderr)
            return aid, None

    novos, velas = {}, {}
    with ThreadPoolExecutor(4) as ex:
        for aid, s in ex.map(um, lote):
            if s:
                novos[aid] = s
    validos = {a[0] for a in alvo}
    series = {k: v for k, v in s_ant.items() if k in validos}
    series.update(novos)
    dados = {'geradoEm': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'dia0': DIA0, 's': series}
    json.dump(dados, open(HIST_SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('historico:', len(novos), 'renovados de', len(lote), '·', len(series), 'ativos ·', os.path.getsize(HIST_SAIDA), 'bytes')
    todas = {k: v for k, v in v_ant.items() if k in validos}
    todas.update(velas)
    lotes = {}
    for k, v in todas.items():
        lotes.setdefault(_hv_lote(k), {})[k] = v
    for L, d in lotes.items():
        json.dump(d, open(os.path.join(HV_DIR, L + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('velas do historico:', len(velas), 'renovadas ·', len(todas), 'ativos em', len(lotes), 'lotes')


def _hv_lote(aid):
    """Lote das velas: a inicial do ticker (A-Z), ou '0' para o resto."""
    c = str(aid or '0')[:1].upper()
    return c if 'A' <= c <= 'Z' else '0'


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


def fred(serie, anos=6):
    """Serie diaria do FRED (Fed de St. Louis) pelo CSV publico: [[ts_ms, valor], ...]."""
    ini = (datetime.now(BRT) - timedelta(days=int(anos * 365.25) + 40)).strftime('%Y-%m-%d')
    url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=' + serie + '&cosd=' + ini
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/csv'})
    with urllib.request.urlopen(req, timeout=30) as r:
        linhas = r.read().decode('utf-8').strip().splitlines()
    out = []
    for l in linhas[1:]:
        d, _, v = l.partition(',')
        try:
            val = float(v)
        except ValueError:
            continue
        dt = datetime.strptime(d.strip(), '%Y-%m-%d').replace(hour=12, tzinfo=BRT)
        out.append([int(dt.timestamp() * 1000), val])
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
        ('selic', {'nome': 'Selic', 'simbolo': 'Meta Copom', 'grupo': 'juros', 'tipo': 'taxa', 'casas': 2,
                   'prefixo': '', 'sufixo': '% a.a.', 'fonte': 'Banco Central (SGS 432, 11 e 4390)'}),
        ('ipca', {'nome': 'IPCA', 'simbolo': '12 meses · IBGE', 'grupo': 'juros', 'tipo': 'taxa', 'casas': 2,
                  'prefixo': '', 'sufixo': '% em 12 meses', 'fonte': 'IBGE via Banco Central (SGS 433 e 13522)'}),
        ('fed', {'nome': 'Juros EUA', 'simbolo': 'Fed funds · FOMC', 'grupo': 'juros', 'tipo': 'taxa', 'casas': 2,
                 'prefixo': '', 'sufixo': '% a.a.', 'fonte': 'Federal Reserve via FRED (DFEDTARU, DFEDTARL e DFF)'}),
    ]
    for aid, base in defs:
        ant = (anterior.get('series') or {}).get(aid) or {}
        s = dict(base)
        for c in ('diario', 'mensal', 'indice', 'ultimo', 'anterior', 'em', 'mudouEm', 'diarioEm', 'inferior'):
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
            elif aid == 'fed':
                teto = [p for p in fred('DFEDTARU') if datetime.fromtimestamp(p[0] / 1000, BRT).weekday() < 5]
                piso = fred('DFEDTARL')
                efetiva = fred('DFF')  # taxa efetiva diaria (dias corridos, base 360)
                idx, v, por_mes = [], 1.0, {}
                for ts, r in efetiva:
                    f = 1 + r / 36000
                    v *= f
                    d = datetime.fromtimestamp(ts / 1000, BRT)
                    m = (d.year, d.month)
                    por_mes[m] = por_mes.get(m, 1.0) * f
                    if d.weekday() < 5:
                        idx.append([ts, float('%.10g' % v)])
                hoje = datetime.now(BRT)
                s['mensal'] = [[int(datetime(y, mm, 1, 12, tzinfo=BRT).timestamp() * 1000), round((f - 1) * 100, 4)]
                               for (y, mm), f in sorted(por_mes.items()) if (y, mm) != (hoje.year, hoje.month)]
                s['indice'] = idx
                s['diario'] = teto
                s['inferior'] = piso[-1][1] if piso else None
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
    extra = extras()
    try:
        req = urllib.request.Request(MAX_URL + '?t=' + str(int(time.time())), headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode('utf-8'))
        if isinstance(j.get('s'), dict):
            MAX_ANT.update(j['s'])
            json.dump(j, open(MAX_SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    except Exception as e:
        print('maximo anterior indisponivel:', type(e).__name__, str(e)[:80])
    try:
        coletar_historico({a[0] for a in ATIVOS + extra})
    except Exception as e:
        print('historico falhou:', type(e).__name__, str(e)[:120], file=sys.stderr)
    with ThreadPoolExecutor(4) as ex:
        series = dict(ex.map(lambda a: coletar_ativo(a, anterior), ATIVOS + extra))
    for a in extra:
        series[a[0]]['extra'] = True
    mx = {k: v for k, v in MAX_ANT.items() if k in series}
    mx.update(MAXIMO)
    if mx:
        json.dump({'geradoEm': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'dia0': DIA0, 's': mx},
                  open(MAX_SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print('maximo:', len(MAXIMO), 'renovados ·', len(mx), 'ativos ·', os.path.getsize(MAX_SAIDA), 'bytes')
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
