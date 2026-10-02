# story-repost-instagram

Worker do **Quase Nada Bots** que reposta **peças disponíveis do brechó** no story das
contas — a estratégia de **vitrine**: conta que queimou o follow ainda tem seguidores que
veem story, então ela passa a divulgar o estoque (sorteia uma peça disponível e reposta o
post dela como card).

## Fonte das peças: o app do brechó
Em vez de raspar o destaque "Disponíveis" do Instagram (briga com o IG: `login_required` na
API mobile, leitura flaky no web), o worker pergunta pro **próprio app do brechó** — cada
peça lá já guarda o `code` do post do IG. Pega só as **disponíveis (não vendidas) que têm
drop e têm code** (`GET {BRECHO_API_URL}/brecho/pecas`, filtrado aqui), sorteia, e reposta.
A foto que o brechó já tem da peça (`imagem_url`) vira o fundo desfocado do story.

Precisa no `.env` do server: `BRECHO_API_URL` e `BRECHO_API_TOKEN`.

Cada conta tem o próprio ciclo (não repete peça até postar todas), então contas diferentes
mostram peças diferentes. `fonte = "proprios"` volta ao modo antigo (últimos posts da conta).

Diferente dos outros workers, este **não usa Playwright/Chromium**: usa a
[`instagrapi`](https://github.com/subzeroid/instagrapi) (API privada do IG, HTTP puro),
então é **leve** (ideal pra VM de 1GB). Loga por **`sessionid`** (reaproveita a sessão que o
app já tem — sem senha) e roteia pelo **mesmo proxy residencial** (`socks5://127.0.0.1:1080`)
dos outros workers, pra sair do mesmo IP de sempre.

## Como uma run funciona
Uma run = **uma conta** (a ativa) ou um **lote** (várias contas, uma de cada vez — no app,
"Rodar em lote", com os chips de **grupo** pra marcar só as contas de um grupo, ex: Vitrine).
O brechó é lido **uma vez** por run. Em cada conta:

0. **Abre** (se `video_intro`, ligado no aleatório) com o vídeo `assets/intro.mp4`
   ("confiram as peças disponíveis no destaque") — precisa do `moviepy` 2.x no venv;
1. **Limpa** — apaga os stories que este bot postou nela (< 24h) cuja peça vendeu;
2. **Escolhe** até `quantos_posts` peças (padrão 10) conforme o modo:
   - **aleatório** — entre todas as disponíveis (o último drop incluso);
   - **drop novo** — só as disponíveis do **último drop postado** (o drop mais recente que já
     tem peça com `postado_em`);

   "Drop" aqui é igual ao app do brechó: os **manuais** (tabela drops) **e** os do
   **histórico** (peças do scraper sem drop manual, agrupadas pela data do post). Peça
   manual que nunca entrou em drop fica de fora;
   sorteadas, **sem repetir peça até a conta postar todas** daquele ciclo. O ciclo é por conta
   e por modo, e é recalculado a cada run sobre as disponíveis do momento — drop novo no meio
   só soma peças, peça vendida some, nada quebra;
3. **Posta** com 1–7s entre um story e outro (`delay_post`).

Conta barrada (`login_required`, checkpoint…) é pulada no lote e aparece no fim. Estado por
conta em `output/state-<uid>.json` (`ciclos` + `stories` das últimas 48h).

## O card é desenhado pelo worker
Pela API, o "post anexado" ao story é só a **área tocável** que abre o post: o card bonito
do "compartilhar no story" é desenhado pelo app do celular de quem compartilha, não pelo IG
(testado: mesmo com dono do post + `media_simple` certos, o story sai só com o fundo). Então o
worker desenha o card na imagem (Pillow) e encaixa o post tocável exatamente em cima.

Dois estilos de card (`estilo`):
- **vitrine** (padrão, pra captar cliente) — fundo laranja do brechó, o card de post, uma
  **etiqueta de preço + tamanho** (campo `venda`/`tamanho` da peça) na letra da logo e uma
  chamada pra ação embaixo (`texto` do modo, ou "comente “fila” para garantir a sua!").

### Etiqueta de preço (`etiqueta.py`)
O texto da etiqueta é decidido por **regras em ordem** (a 1ª que se aplica ganha), lendo a
descrição da peça (texto manual do brechó, senão a legenda do post):

1. **várias ofertas** na descrição → preço do pacote em destaque (qualquer palavra de pacote:
   conjunto, kit, combo, os dois…) + o avulso ("OU R$ 30 CADA" + tamanhos, ou uma linha por
   peça quando os preços diferem). Sem pacote → "A PARTIR DE". Parte marcada **VENDIDO** sai
   e o pacote some (quebrou); se sobra uma peça, vira etiqueta simples dela.
2. **peça simples** → preço + "TAM X" (sem tamanho → só o preço).
3. **sem preço** → sem etiqueta.

A leitura é genérica (linha a linha: cada preço pega o nome/tamanho mais próximo acima ou na
mesma linha), então não depende da ordem dos blocos nem do separador — aceita "R$:30", "R$ 30",
"30 reais", "conjunto: R$ 50" etc. Caso novo = uma função nova em `REGRAS`.
Testes: `python test_etiqueta.py` (sem rede).

### Posts do brechó (legendas)
O worker lê os últimos ~300 posts do brechó (~2 min) e guarda em `output/posts_brecho.json`
por 12h. Serve pra: ligar ao post a peça manual (sem `code`) pela tag `#p<num>`; dar a
descrição pra etiqueta; dar a **foto do story = 1ª imagem do post** (a foto do app pode ser
a crua, na peça manual — ela fica só de reserva); e **pular peça cujo post já diz "| ❌VENDIDO❌"** (o app às vezes
atrasa). Peça que não aparece em nenhuma legenda fica de fora.
- **original** — cópia do card do Insta (fundo = foto desfocada, sem preço).

Fontes em `assets/fonts`: Inter (OFL) pro card, Walter Turncoat (Apache 2.0) pra letra à mão.
A foto de perfil do autor vem do IG (`user_info_v1`, cache de 1 dia em `output/avatar-<uid>.jpg`).

## Dois modos
- **repostar drop** (`repost_card = true`) — reposta o post embutido como **card** (o "adicionar
  ao story" clássico), sobre um fundo desfocado do próprio post.
- **imagem cheia** (`repost_card = false`) — posta a **imagem** do post em tela cheia (9:16).

Ambos aceitam **texto** sobreposto opcional (ex: `NOVO DROP -20%`) e um **link** opcional.

## Config (por modo — editável no app)
| campo | o quê |
|-------|-------|
| `selecao` | `aleatorio` (todas as disponíveis) ou `drop_novo` (só o último drop postado) |
| `fonte` | `brecho` (peças disponíveis c/ drop — padrão) ou `proprios` (posts da conta) |
| `repost_card` | card embutido (on) ou imagem cheia (off) |
| `estilo` | `vitrine` (laranja + preço + chamada) ou `original` (igual o Insta) |
| `mostrar_preco` | vitrine: etiqueta com valor/tamanho da peça |
| `quantos_posts` | quantos dos últimos posts postar (1 = só o mais recente) |
| `texto` | texto sobreposto (opcional) |
| `link` | sticker de link (opcional; exige conta elegível) |
| `delay_post` | delay entre um story e o próximo |
| `active_hours` | janela de horário (ini==fim = sem janela) |

Dedup: cada post só vai pro story **uma vez** (marco em `output/state-<conta>.json`).

## Rodar
A conta que **posta** é a que está logada (o backend injeta `IG_SESSION_FILE`). Pra o brechó,
selecione o `@brechoquasenadaa` antes de rodar. Local:

```
python main.py --modo "repostar drop"            # roda de verdade
python main.py --modo "imagem cheia" --dry-run   # simula (não posta)
python main.py --listar-modos                    # mostra os modos
```

## Dependências
`instagrapi`, `Pillow`, `PySocks` — no mesmo venv do backend.

## Quais contas conseguem postar
Testado 01/10/2026 (card do post do brechó, postado e apagado): segue2, 4, 5, 6, 7 e 11
**postam**; a **segue3 não** (`login_required` até em story simples — a sessão dela tá barrada
pra escrita pela API privada; reconectar pode resolver). Quando isso acontece o worker para
com mensagem clara em vez de tentar peça por peça.

## Segurança
API privada = mesmo tipo de risco dos outros bots (contra os ToS do IG). Postar o próprio
story é comportamento normal (bem menos suspeito que follow/DM em massa). Rode em **cadência
humana** (1-2 stories/dia) e só na conta do brechó.
