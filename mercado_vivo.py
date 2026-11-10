#!/usr/bin/env python3
"""Cotações quase em tempo real para a seção Mercado do Hub (roda no GitHub Actions).

Durante o pregão, a cada ~60 s: lê as cotações (Yahoo Finance, com o atraso
normal de cada bolsa) e as taxas do DI1 (B3) e grava um documento pequeno no
Firestore do projeto rico-hub, que o Hub lê direto (mesmo caminho do Pipeline).
Dados públicos de mercado. Uso: python mercado_vivo.py <minutos>
"""
import json, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import mercado_coletar as M

DOC = ('https://firestore.googleapis.com/v1/projects/rico-hub/databases/(default)/documents/'
       'ricoPipeline/v3-mercado-ao-vivo')
INTERVALO = 60
BRT = timezone(timedelta(hours=-3))


def http_json(url, metodo='GET', corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        'User-Agent': M.UA, 'Accept': 'application/json', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))


def spark(simbolos):
    """{simbolo: (ultimo, anterior, [[ts, v], ...])} pelo endpoint spark (vários de uma vez)."""
    url = ('https://query1.finance.yahoo.com/v8/finance/spark?symbols=' + urllib.parse.quote(','.join(simbolos))
           + '&range=1d&interval=5m')
    j = http_json(url)
    out = {}
    itens = []
    if isinstance(j, dict) and 'spark' in j:  # formato antigo
        for r in (j['spark'].get('result') or []):
            resp = (r.get('response') or [{}])[0]
            meta = resp.get('meta', {})
            closes = ((resp.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
            itens.append((r.get('symbol'), resp.get('timestamp') or [], closes,
                          meta.get('regularMarketPrice'), meta.get('chartPreviousClose', meta.get('previousClose'))))
    elif isinstance(j, dict):  # formato atual: {simbolo: {...}}
        for sym, r in j.items():
            if not isinstance(r, dict):
                continue
            itens.append((r.get('symbol', sym), r.get('timestamp') or [], r.get('close') or [],
                          None, r.get('chartPreviousClose', r.get('previousClose'))))
    for sym, ts, closes, ultimo, anterior in itens:
        pts = [[int(t) * 1000, round(float(c), 6)] for t, c in zip(ts, closes) if c is not None]
        if ultimo is None and pts:
            ultimo = pts[-1][1]
        if ultimo is not None:
            out[sym] = (ultimo, anterior, pts)
    return out


def um_a_um(simbolos):
    def f(sym):
        try:
            pts, meta = M.yahoo(sym, '1d', '5m')
            u = meta.get('regularMarketPrice')
            return sym, (u if u is not None else (pts[-1][1] if pts else None),
                         meta.get('chartPreviousClose', meta.get('previousClose')), pts)
        except Exception:
            return sym, None
    with ThreadPoolExecutor(4) as ex:
        return {s: v for s, v in ex.map(f, simbolos) if v and v[0] is not None}


_extras = {'em': 0, 'lista': []}


def ativos():
    """Ativos fixos + os acrescentados na lista do Hub (relidos a cada 5 min)."""
    if time.time() - _extras['em'] > 300:
        _extras['lista'] = M.extras()
        _extras['em'] = time.time()
    return M.ATIVOS + _extras['lista']


def ciclo(modo):
    lista = ativos()
    simbolos = [a[2] for a in lista]
    cot = {}
    if modo['spark']:
        try:
            for i in range(0, len(simbolos), 20):
                cot.update(spark(simbolos[i:i + 20]))
        except Exception as e:
            print('spark indisponível, uso a consulta por ativo:', type(e).__name__, str(e)[:80])
            modo['spark'] = False
    faltam = [s for s in simbolos if s not in cot]
    if faltam:
        cot.update(um_a_um(faltam))
    q = {}
    for aid, nome, sym, *_ in lista:
        if sym in cot:
            u, ant, pts = cot[sym]
            q[aid] = {'u': u, 'a': ant, 'p': pts[-120:]}
    di = {}
    try:
        j = M.get_json('https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1')
        for x in j.get('Scty', []):
            sym = x.get('symb', '')
            if sym[3:] in M.DI_VENCTOS:
                sq = x.get('SctyQtn') or {}
                t = sq.get('curPrc') or sq.get('avrgPric')
                if t:
                    di[sym] = {'t': t, 'a': sq.get('prvsDayAdjstmntPric')}
    except Exception as e:
        print('DI1 indisponível:', type(e).__name__)
    return {'ts': int(time.time() * 1000), 'q': q, 'di': di}


def gravar(dados):
    corpo = {'fields': {'envelope': {'stringValue': json.dumps(dados, separators=(',', ':'))},
                        'format': {'integerValue': '3'}}}
    http_json(DOC, 'PATCH', corpo)


def pregao():
    """Dias úteis, das 9h40 às 18h30 de Brasília (cobre B3, DI e o fechamento de Nova York)."""
    a = datetime.now(BRT)
    return a.weekday() < 5 and (9, 40) <= (a.hour, a.minute) <= (18, 30)


def main():
    minutos = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    fim = time.time() + minutos * 60
    modo = {'spark': True}
    n = erros = 0
    # O GitHub às vezes dispara o agendamento com horas de atraso (já de noite). Fora do
    # pregão o turno grava uma única vez, para deixar o fechamento certo, e encerra.
    if not pregao():
        try:
            dados = ciclo(modo)
            if dados['q'] or dados['di']:
                gravar(dados)
                print(datetime.now(BRT).strftime('%H:%M'), 'fora do pregão: gravado uma vez', len(dados['q']), 'ativos')
        except Exception as e:
            print('fora do pregão, sem gravar:', type(e).__name__, str(e)[:160])
        return
    while time.time() < fim and pregao():
        t0 = time.time()
        try:
            dados = ciclo(modo)
            if dados['q'] or dados['di']:
                gravar(dados)
                n += 1
                if n == 1 or n % 30 == 0:
                    print(datetime.now(BRT).strftime('%H:%M'), 'gravado', len(dados['q']), 'ativos,', len(dados['di']), 'DI')
        except Exception as e:
            erros += 1
            print('erro no ciclo:', type(e).__name__, str(e)[:160])
            if erros >= 10 and n == 0:
                sys.exit('não consegui gravar nenhuma vez — encerro')
        time.sleep(max(5, INTERVALO - (time.time() - t0)))
    print('fim:', n, 'gravações,', erros, 'erros')


if __name__ == '__main__':
    main()
