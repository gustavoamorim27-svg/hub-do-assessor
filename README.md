# Hub do Assessor

Ferramentas de apoio comercial para assessoria de investimentos.

**No ar:** https://gustavoamorim27-svg.github.io/hub-do-assessor/ (acesso com senha)

## Como funciona

- `index.html` é só a tela de login.
- O Hub em si (arquivo único, ~5 MB, com todo o CSS e JavaScript embutidos) fica em `hub.enc`, compactado e criptografado com AES-256-GCM. A chave sai da senha via PBKDF2-SHA256.
- A tela de login baixa o `hub.enc`, abre com a senha e carrega o Hub no próprio navegador. Sem a senha, o arquivo é ilegível.
- "Lembrar neste aparelho" guarda só a chave derivada no navegador. O botão **Sair e bloquear**, no menu, apaga essa chave.
- Os dados do usuário continuam no `localStorage` do navegador (prefixo `hub:v2:`). Nada é enviado para servidor.

## Atualizar o Hub

```
HUB_SENHA='…' python3 cofre.py abrir  hub.enc hub-src.html   # descriptografa
# editar hub-src.html
HUB_SENHA='…' python3 cofre.py fechar hub-src.html hub.enc   # criptografa de novo
```

Nunca suba o `hub-src.html` nem a senha para o repositório. O `fechar` mantém o sal do arquivo, então quem marcou "lembrar" continua entrando direto depois de uma atualização.

## Radar de mercado (notícias e Morning Call)

- O workflow `.github/workflows/publicar.yml` publica o site no GitHub Pages a cada push e, nos dias úteis, a cada 15–30 min.
- Antes de publicar, `radar_coletar.py` lê os feeds (manchetes, Morning Call e podcast da XP, relatórios Raio-XP) e grava `radar.enc` ao lado do Hub. Feed vazio ou bloqueado cai para o Google Notícias do mesmo site.
- O Hub lê o `radar.enc` do próprio endereço (passa pela rede da Rico) e só usa o rss2json de reserva.
- `radar.enc` é criptografado com a chave pública `radar_chave.pem`; a chave privada fica só dentro do `hub.enc`.
- Para rodar na hora: aba Actions → "Publicar Hub e Radar" → Run workflow. O Pages precisa estar com a fonte "GitHub Actions".

---

Material de apoio interno. Não constitui recomendação de investimento.
