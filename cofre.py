#!/usr/bin/env python3
"""Cofre do Hub: o conteúdo do Hub fica criptografado em hub.enc.

  HUB_SENHA=... python3 cofre.py abrir  hub.enc  saida.html
  HUB_SENHA=... python3 cofre.py fechar entrada.html hub.enc

Formato: b"HUB1" | iteracoes (uint32 BE) | sal (16) | iv (12) | AES-256-GCM(gzip(html)).
Ao fechar, o sal do hub.enc existente é mantido, assim quem marcou
"lembrar neste aparelho" não precisa digitar a senha de novo a cada atualização.
A senha nunca fica no repositório.
"""
import gzip, os, struct, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

MAGIC = b"HUB1"
ITER = 310000


def chave(senha, sal, it):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=it).derive(senha.encode("utf-8"))


def senha():
    s = os.environ.get("HUB_SENHA")
    if not s:
        sys.exit("defina HUB_SENHA")
    return s


def abrir(entrada, saida):
    b = open(entrada, "rb").read()
    assert b[:4] == MAGIC, "arquivo não é um cofre do Hub"
    it = struct.unpack(">I", b[4:8])[0]
    sal, iv, ct = b[8:24], b[24:36], b[36:]
    html = gzip.decompress(AESGCM(chave(senha(), sal, it)).decrypt(iv, ct, None))
    open(saida, "wb").write(html)
    print("aberto:", saida, len(html), "bytes")


def fechar(entrada, saida):
    html = open(entrada, "rb").read()
    sal, it = os.urandom(16), ITER
    if os.path.exists(saida):
        old = open(saida, "rb").read()
        if old[:4] == MAGIC:
            it = struct.unpack(">I", old[4:8])[0]
            sal = old[8:24]
    iv = os.urandom(12)
    ct = AESGCM(chave(senha(), sal, it)).encrypt(iv, gzip.compress(html, 9), None)
    open(saida, "wb").write(MAGIC + struct.pack(">I", it) + sal + iv + ct)
    print("fechado:", saida, 36 + len(ct), "bytes")


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("abrir", "fechar"):
        sys.exit(__doc__)
    (abrir if sys.argv[1] == "abrir" else fechar)(sys.argv[2], sys.argv[3])
