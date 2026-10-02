"""Testes da etiqueta (sem rede, sem IG): python test_etiqueta.py"""
import etiqueta as e


def txts(peca, texto=""):
    return [t for t, *_ in e.linhas(peca, texto)]


CASOS = [
    ("conjunto no fim, preços iguais (formato do brechó)",
     {"venda": 50},
     "| conjunto shein\n\ntop\ncondição: 10/10\ntam.: g (l 35cm c 38cm)\nR$:30\n—————————\nsaia\n"
     "condição: 10/10\ntam.: m (l 35cm c 34cm)\nR$:30\n\ncintura ajustável\n—————————\nconjunto\nR$:50\n\n"
     "comente \"fila\"\n.\n.\n#brechoonline #brecho #p440",
     ["R$ 50", "CONJUNTO", "OU R$ 30 CADA", "TOP G · SAIA M"]),
    ("conjunto no fim, preços diferentes",
     {"venda": 80},
     "| tracksuit real madrid\n\nblusa \ncondição: 10/10\ntam.: m (l 55cm c 71)\nR$:50\n—————————\ncalça\n"
     "condição: 9/10\ntam.: m (l 38cm c 97cm)\nR$:40\n\ncintura ajustável, leve mancha\n—————————\nconjunto\nR$:80",
     ["R$ 80", "CONJUNTO", "OU AVULSO", "BLUSA M · R$ 50", "CALÇA M · R$ 40"]),
    ("conjunto PRIMEIRO, inline, sem separador",
     {"venda": 70},
     "conjunto: R$ 70\n\nbody tam: p R$ 40\nshort\ntam.: 38\nR$ 40",
     ["R$ 70", "CONJUNTO", "OU R$ 40 CADA", "BODY P · SHORT 38"]),
    ("kit com 'reais' e 'os dois por'",
     {"venda": 0},
     "camiseta 1\ntamanho: g\n25 reais\n\ncamiseta 2\ntamanho: m\n30 reais\n\nos dois por 45 reais",
     ["R$ 45", "OS DOIS", "OU AVULSO", "CAMISETA 1 G · R$ 25", "CAMISETA 2 M · R$ 30"]),
    ("várias peças sem pacote",
     {"venda": 20},
     "cinto preto R$ 20\ncinto marrom R$ 25",
     ["A PARTIR DE", "R$ 20", "CINTO PRETO · R$ 20", "CINTO MARROM · R$ 25"]),
    ("peça simples com tamanho", {"venda": 25, "tamanho": "m"}, "", ["R$ 25", "TAM M"]),
    ("peça simples SEM tamanho", {"venda": 30, "tamanho": None}, "", ["R$ 30"]),
    ("descrição de 1 preço = peça simples", {"venda": 25, "tamanho": "p"},
     "| blusa\ncondição: 10/10\ntam.: p\nR$:25", ["R$ 25", "TAM P"]),
    ("sem preço no cadastro, preço na descrição", {"venda": 0, "tamanho": "g"}, "R$:35", ["R$ 35", "TAM G"]),
    ("sem preço nenhum", {"venda": None}, "", []),
    ("centavos", {"venda": 25.5}, "", ["R$ 25,50"]),
    ("conjunto com uma parte vendida → sobra a outra",
     {"venda": 50},
     "| conjunto shein\n\ntop ❌VENDIDO❌\ntam.: g\nR$:30\n—————————\nsaia\ntam.: m\nR$:30\n—————————\nconjunto\nR$:50",
     ["R$ 30", "SAIA M"]),
    ("kit de 3, um vendido (marcado depois do preço) → avulso das outras",
     {"venda": 60},
     "blusa 1\ntam: p\nR$ 25\n—————\nblusa 2\ntam: m\nR$ 25\nVENDIDA\n—————\nblusa 3\ntam: g\nR$ 30\n—————\nkit R$ 60",
     ["A PARTIR DE", "R$ 25", "BLUSA 1 P · R$ 25", "BLUSA 3 G · R$ 30"]),
]

assert e.post_vendido("| ❌VENDIDO❌\n\ntracksuit real madrid\n…"), "post vendido no título"
assert not e.post_vendido("| conjunto shein\n\ntop ❌VENDIDO❌\nR$:30"), "só uma parte vendida ≠ post vendido"

falhas = 0
for nome, peca, texto, esperado in CASOS:
    obtido = txts(peca, texto)
    ok = obtido == esperado
    falhas += not ok
    print(("ok   " if ok else "FALHA"), nome, "" if ok else f"\n      esperado {esperado}\n      obtido   {obtido}")
print(f"\n{len(CASOS) - falhas}/{len(CASOS)} ok")
raise SystemExit(1 if falhas else 0)
