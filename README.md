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

---

Material de apoio interno. Não constitui recomendação de investimento.
