# Story Repost + Vitrine — como funciona

Documento completo do bot **Story Repost** e das features de app/backend que entraram junto
com ele (grupos de contas, trava, cronograma automático, lote). É a visão de ponta a ponta:
o que é, por que existe, como o código está organizado e as decisões que moldaram cada parte.

> **Escopo:** o worker vive em `workers/story-repost-instagram/` (repo próprio,
> `ViniciusMateos/story-repost-instagram`, v1.0.0). As partes de app/backend estão no repo
> pai `ViniciusMateos/quase-nada-bots` (v1.8.0, OTA 51). Infra: backend + workers no Oracle
> **server 2** (`136.248.95.162`, backend `:8010`); o app do **brechó** no **server 1**
> (`:8020`).

---

## 1. A ideia: contas-vitrine

Algumas contas de Instagram **queimaram o follow** — bateram o teto de seguir/pedir e não
servem mais pra captação (DM só vai pra quem seguiu de volta, então follow morto = inútil pra
captar). Mas elas **ainda têm seguidores que veem story**.

A sacada: em vez de deletar, essas contas viram **vitrine**. Elas repostam no story as **peças
disponíveis do brechó**, divulgando o estoque. Captam **venda**, não cliente.

- As peças vêm do **app do brechó** (não do Instagram) — ver seção 4.
- Cada conta posta um tanto de peças por run, sorteadas, sem repetir até postar todas.
- O card parece um **repost de post** de verdade, pra pessoa tocar e ir ver a peça.

Grupos no app organizam isso: um grupo **Vitrine** (contas queimadas rodando story-repost) e um
grupo **Captação** (contas novas rodando follow+DM). Ver seção 8.

---

## 2. Stack e diferença pros outros workers

Diferente dos outros bots (auto-follow, dm-followers, like-repost, human-warmup), que usam
**Playwright/Chromium**, o story-repost usa a **`instagrapi`** (API privada do IG, HTTP puro):

- **Leve** — sem Chromium, ideal pra VM de 1GB.
- **Login por `sessionid`** — reaproveita a sessão que o app já importou (`IG_SESSION_FILE`),
  sem senha, sem captcha.
- **Proxy** `socks5://127.0.0.1:1080` — o mesmo túnel residencial dos outros workers, pra sair
  do mesmo IP de sempre.

Dependências no venv do backend: `instagrapi==3.0.16`, `Pillow`, `PySocks`, `moviepy>=2,<3`
(pro vídeo de abertura — a instagrapi usa `mp.VideoFileClip` da API 2.x).

### Quais contas conseguem postar
Testado 01/10/2026: segue2, 4, 5, 6, 7 e 11 **postam**; a **segue3 não** (`login_required` até
em story simples — sessão barrada pra escrita; reconectar pode resolver). O `photo_upload_to_story`
funciona via sessionid em conta saudável — **não precisa de login completo** (senha), só a sessão.

---

## 3. O card é desenhado pelo worker (não é repost nativo)

Esta é a decisão central do visual, e a que mais custou pra descobrir.

**O "post anexado" (`StoryMedia`) da API é só uma área tocável.** No app do IG, quem desenha
aquele card bonito do "compartilhar no story" (foto de perfil, moldura, carrossel) é o **próprio
celular de quem compartilha**. Pela API, o IG **não desenha nada** — testado com o dono do post
e `media_simple_<pk>` certinhos, e o story saía **só com o fundo** (preto, no começo). Não tem
como forçar o card nativo pela API.

**Solução:** o worker **desenha o card na imagem** com Pillow (`ig.py`, `_montar`), e encaixa o
post tocável (`StoryMedia` com `x,y,width,height` = a geometria do card desenhado) por cima. Tocar
no card leva ao post de verdade, com o dono registrado certo (`user_id`).

### Dois estilos de card (`estilo`)
- **vitrine** (padrão, pra captar) — fundo **laranja do brechó** (#FF8234) com um brilho suave no
  meio, o card de post branco no centro, **etiqueta de preço** no canto e uma **chamada pra ação**
  embaixo. É o que faz a pessoa achar que é post e tocar.
- **original** — cópia fiel do card do Insta (fundo = a foto desfocada, sem preço). Foi medido num
  print do app: card branco quase reto (~74% da largura), cabeçalho com foto de perfil + @, foto
  em até 3:4, rodapé "**@autor** | nome da peça".

### Detalhes do desenho
- **Foto de perfil real** do brechó: `user_info_v1` (passa via sessionid), cache de 1 dia em
  `output/avatar-<uid>.jpg`.
- **Foto do post** = SEMPRE a 1ª imagem do post (igual o feed), não a foto do app (que na peça
  manual pode ser a foto crua no chão). A do app fica como reserva.
- **Fontes** em `assets/fonts/`: **Inter** (OFL) pro card, **Walter Turncoat** (Apache 2.0) pra
  letra à mão da etiqueta — escolhida por ser a mais parecida com a letra da logo do brechó.
- **Chamada pra ação** padrão: "COMENTE "FILA" PARA GARANTIR A SUA!" (o campo `texto` do modo
  substitui). As aspas são desenhadas à parte e subidas, porque a Walter Turncoat as desenha
  baixas demais.
- Fotos 3:4 aparecem inteiras (o IG aceita até 3:4); a etiqueta nunca sobe pra barra do story.

---

## 4. De onde vêm as peças (`brecho.py`)

A fonte é o **app do brechó**, não o Instagram. Raspar o destaque "Disponíveis" do IG dava
`login_required` na API mobile e era flaky no web — abandonado. O brechó já guarda, em cada peça,
o `code` do post, a imagem e o status.

### Endpoint
`GET {BRECHO_API_URL}/brecho/pecas` com `Authorization: Bearer {BRECHO_API_TOKEN}`.
Do server2, a URL é `https://quasenadaserver1.duckdns.org/brecho` + `/brecho/pecas` (prefixo
duplo; a forma simples dá 404). URL e token ficam no `.env` do server2.

### Drops: manual + histórico (a parte que estava contando errado)
O app do brechó tem **dois tipos de drop**, e o bot tem que considerar os dois (senão conta ~37
em vez das ~78 reais, que é o número do destaque "Disponíveis"):
- **manual** — peça com `drop_id` (tabela `drops` do brechó). Chave interna: `m<id>`.
- **histórico** — peça do **scraper** sem `drop_id`, agrupada pela **data do post** (`postado_em`).
  Chave interna: `h<data>`.

Peça manual que **nunca entrou em drop** (17 delas) fica de fora — não tem post.

`ultimo_drop()` = o drop postado mais recente (manual ou histórico); empate de data → manual
ganha. É o que o modo "drop novo" usa.

### Ligar peça ao post + descrição (`ligar_posts`)
Peça manual (ex: conjunto) **não tem `code`** no brechó (o scraper não liga). O bot acha o post
pela tag **`#p<num>`** que o brechó põe na legenda. Também pega dali:
- a **descrição** (template manual do brechó, senão a legenda do post) → alimenta a etiqueta;
- a **foto** do post (1ª imagem) → o card;
- pula peça cujo post já diz "**| ❌VENDIDO❌**" na legenda (o app às vezes atrasa).

### Leitura dos posts do brechó (cache `output/posts_brecho.json`)
O brechó tem ~400 posts e as peças do histórico são antigas, então ler todos é caro (~3 min).
Por isso é **incremental**:
- **completa** (todos os posts) — só **sem cache** ou quando **falta uma peça** que o bot precisa
  (no máx 1x a cada 6h);
- **curta** (60 mais novos) — a cada 12h, pra pegar post novo e legenda editada (VENDIDO).

A **foto de cada peça é salva no server** na 1ª vez em `output/fotos/<code>.jpg` — o link de foto
do IG expira, então guardar local evita reler tudo só pra renovar link.

---

## 5. A etiqueta de preço é modular (`etiqueta.py`)

Pedido explícito: **nada específico de um caso** ("imagina se surge outro conjunto com posição
diferente"). Então a etiqueta é um módulo separado (o `ig.py` só desenha o que ele decide), com
**regras em ordem** — a 1ª que se aplica ganha:

1. **várias ofertas** na descrição → preço do **pacote** (qualquer palavra: conjunto, kit, combo,
   "os dois"…) em destaque + o avulso ("OU R$ 30 CADA" + tamanhos, ou uma linha por peça quando
   os preços diferem; sem pacote → "A PARTIR DE"). Parte marcada **VENDIDO** sai e quebra o pacote.
2. **peça simples** → preço + "TAM X" (sem tamanho → só o preço).
3. **sem preço** → sem etiqueta.

A leitura da descrição é **genérica** (linha a linha: cada preço pega o nome/tamanho mais próximo
acima ou na mesma linha), então **não depende da ordem dos blocos nem do separador**. Aceita
"R$:30", "R$ 30", "30 reais", "conjunto: R$ 50" etc. **Caso novo = uma função nova em `REGRAS`.**

Testes sem rede: `python test_etiqueta.py` (13 casos).

---

## 6. Fluxo de uma run (`main.py`)

Uma run = **uma conta** (a ativa/escolhida) ou um **lote** (várias contas, uma de cada vez — o
backend passa a lista em `IG_LOTE_CONTAS`, igual o like-repost). O brechó é lido **uma vez** por
run. Em cada conta:

0. **Abre** (se `video_intro`, ligado no modo aleatório) com `assets/intro.mp4` ("confiram as
   peças disponíveis no destaque") — o vídeo que o Vinicius sempre posta antes das peças.
1. **Limpa** — apaga os stories que ESTE bot postou nela (< 24h) cuja peça **vendeu** (não está
   mais disponível, ou o post virou VENDIDO).
2. **Escolhe** até `quantos_posts` peças (padrão 10) conforme a `selecao` do modo:
   - **aleatório** → entre TODAS as disponíveis (o último drop incluso);
   - **drop novo** → só as disponíveis do **último drop postado**;
   sorteadas, **sem repetir peça até a conta postar todas** daquele ciclo.
3. **Posta** com **1–7s** entre um story e outro (`delay_post`) e marca no ciclo.

Conta barrada (`login_required`, checkpoint…) é **pulada** no lote e aparece no fim.

### Por que o ciclo não quebra com drop no meio
O ciclo é **por conta e por modo**, e é **recalculado a cada run** sobre as disponíveis do
momento — não é uma fila fixa montada lá atrás. Drop novo entrando só **soma** peças novas, peça
vendida **some**, nada precisa reiniciar. Estado por conta em `output/state-<uid>.json`
(`ciclos` por modo + `stories` postados nas últimas 48h, pra a limpeza).

---

## 7. Modos (`perfis.py`) e campos no app

Dois modos builtin:
- **aleatório** (padrão) — `selecao=aleatorio`, `video_intro=true`.
- **drop novo** — `selecao=drop_novo`, `video_intro=false`.

Campos editáveis no app (tela Editar modo), além dos dois acima:
| campo | o quê |
|-------|-------|
| `selecao` | o que postar: aleatório (todas) ou drop novo (último drop postado) |
| `video_intro` | posta o vídeo de abertura antes das peças |
| `quantos_posts` | stories por run, por conta (padrão 10) |
| `repost_card` | card embutido (on) ou imagem cheia (off) |
| `estilo` | `vitrine` (laranja + preço + chamada) ou `original` (igual o Insta) |
| `mostrar_preco` | etiqueta com valor/tamanho |
| `texto` | chamada embaixo do card (vazio = "comente "fila"…") |
| `link` | sticker de link (opcional) |
| `delay_post` | segundos entre um story e o próximo (padrão 1–7) |
| `active_hours` | janela de horário |

---

## 8. Features de app/backend que entraram junto (repo pai, v1.8.0)

### Grupos de contas
Etiqueta por conta (ex: **Vitrine**, **Captação**), salva em `sessions/accounts.json`
(`grupos: [nome]` por conta + lista no topo). CRUD em `/grupos` (GET/POST/PUT/DELETE). Na tela de
**Contas**: chips de grupo — tocar edita quem está nele (checkbox por conta), segurar renomeia/apaga.
Na tela do **bot**: o lote (agora também no story-repost) tem chips de grupo que pré-marcam só as
contas vivas do grupo. No **Hub** e no **seletor de conta**, as contas aparecem **separadas por
grupo** (+ Avulsas).

### Trava de conta
Campo `travada` no `accounts.json`, endpoint `PUT /accounts/{id}/travada`, **cadeado** na tela de
Contas. Conta travada fica **fora de qualquer automático** (hoje, o aquecimento do cronograma —
mas é genérico: toda automação futura deve checar `accounts.travada(uid)`). Rodar na mão continua
normal. Serve pra conta do brechó, que não deve rodar aquecimento sozinha.

### Cronograma "Rodar automaticamente" (saiu o lembrete)
O switch virou **"Rodar automaticamente"**. Desligado = **pausado** (não roda nada). Ao religar, o
que passou da hora é **pulado** (não roda atrasado) e segue do próximo horário. **O push de
lembrete saiu**: horário que não deu pra rodar é só pulado; o único aviso que sobra é o de
**reconectar** (sessão caída). Conta travada sai do plano.

### Hub: arrastar os bots
Saíram as setas e a barra "Reordenando". Agora é **segurar e arrastar** (`ui/ListaArrastavel.tsx`).
Importante: isso foi feito com **`PanResponder` + `Animated` do RN**, NÃO com Reanimated/gesture-
handler — a versão com worklets empilhou os cards e não seguia o dedo no aparelho. E **tudo no
driver JS** (`useNativeDriver: false`): misturar native driver com `setValue` desincronizava e os
cards ficavam um em cima do outro a cada re-render. A ordem é commitada **na hora que solta**.

### Fix: autofill do login do IG
O autopreenchimento pegava qualquer input de texto (até o de "trocar e-mail") e reescrevia a cada
0,3s por ~9s — o campo se repreenchia sozinho. Agora só age em página com **campo de senha**
(tela de login), preenche cada campo **vazio uma vez** e **para assim que você mexe** num campo.
O mesmo código existe no app do **brechó** (corrigido lá também).

---

## 9. Mapa dos arquivos do worker

| arquivo | papel |
|---------|-------|
| `main.py` | orquestra a run: contexto do brechó, limpeza, seleção, loop de post, lote |
| `brecho.py` | fonte das peças: API do brechó, drops (manual+histórico), ligar post, cache de posts/fotos |
| `etiqueta.py` | o que vai escrito na etiqueta (regras modulares) — sem desenho |
| `ig.py` | wrapper da instagrapi: login, desenho do card (`_montar`), etiqueta, postar foto/vídeo |
| `config.py` | sessão, proxy, flags do modo, paths, `BRECHO_*` |
| `perfis.py` | modos (aleatório/drop novo) + mapa modo→config |
| `safety.py` | logger, delays humanos, janela de horário, `State` (ciclos + stories por conta) |
| `test_etiqueta.py` | testes da etiqueta (sem rede) |
| `assets/fonts/` | Inter (OFL) + Walter Turncoat (Apache) + licenças |
| `assets/intro.mp4` | vídeo de abertura |

Saída (gitignored): `output/` — `state-<uid>.json`, `posts_brecho.json`, `fotos/<code>.jpg`,
`avatar-<uid>.jpg`, `canvas.jpg`/`peca.jpg` (temporários), logs.

---

## 10. Operação

- **Deploy do worker:** só `scp` dos `.py` pro server2 (os workers rodam como subprocesso do
  backend; não precisa restart). `assets/` também por scp.
- **Deploy de backend:** `scp` + `systemctl restart quase-nada-bots.service`. **ANTES de
  reiniciar, checar se tem bot rodando** (GET `/runs` com o Bearer) e abortar se tiver — restart
  mata worker em execução.
- **App:** `eas update --branch preview` (OTA, sem build); subir `OTA_VERSION` +1 a cada update.
- **Rodar no app:** tela Story Repost → "Rodar em lote" → chip do grupo (ex: Vitrine) → escolher
  o modo → Rodar. Uma conta por vez (túnel único).
- **Fim de processo:** push pelo app dos bots (`notify.enviar` no server2).

---

## 11. Decisões e armadilhas (pra não repetir)

- **Card nativo não existe pela API** — o IG não desenha; desenhamos nós (seção 3).
- **Foto tem que vir do post**, não do app — peça manual tem foto crua no app.
- **Drops são 2 tipos** — contar só os manuais dava metade das peças (seção 4).
- **Etiqueta é modular** — caso novo = regra nova, nada hardcoded (seção 5).
- **10 por run é o padrão pedido**, 1–7s entre eles — o Vinicius posta mais rápido na mão; vamos
  testando. Baixar se der bloqueio.
- **Arrastar no RN = PanResponder, não Reanimated**; tudo no mesmo driver (seção 8).
- **Dois `<Modal>` juntos quebram no iOS** — a tela de Contas usa um Modal só, compartilhado entre
  "nova conta" e "nome de grupo".
- **moviepy 2.x** (não 1.x) — a instagrapi 3.0.16 usa a API nova.
- O que **NÃO** foi feito, por decisão: resolver verificação do IG (e-mail/SMS/imagem) automático
  e painel de captura de sessão fora do app. Reconexão continua pelo app, na mão.

---

## 12. Pendências / próximos passos

- Cronograma rodar o story-repost **por grupo** automaticamente (as vitrines) — hoje o cronograma
  só faz aquecimento.
- Avaliar **baixar o limite dos modos de captação** (follow/DM) — as sessões caem muito (ritmo
  alto em conta nova no mesmo IP puxa verificação de e-mail). Era o que estava derrubando as runs
  de auto-follow.
- `polo m.officer` (#p354) e peças sem post ligado ficam de fora até terem post no IG.
