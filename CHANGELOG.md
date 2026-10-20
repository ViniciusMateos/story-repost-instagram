# Changelog

## [1.0.1] — 2026-10-20

### Modificado
- update: guarda a foto de cada peça no servidor e só relê todos os posts quando falta peça (antes relia tudo a cada 3 dias só pra renovar o link da foto)

### Corrigido
- fix: para na hora quando o Instagram restringe os envios da conta ("restricted from uploading") e marca bloqueio no app, em vez de insistir peça a peça

### Documentação
- docs: PROJETO.md com a visão de ponta a ponta do bot

## [1.0.0] — 2026-10-02

### Adicionado
- feat: **fonte = app do brechó** (padrão) — reposta peças **disponíveis com drop** sorteadas, lendo o `code` do post que o brechó já guarda em cada peça (`GET /brecho/pecas` filtrado), em vez de raspar o destaque "Disponíveis" do IG; usa a foto da peça como fundo desfocado; ciclo por conta (não repete até postar todas). `fonte=proprios` mantém o modo de últimos posts da conta
- feat: **card desenhado na imagem** — o post anexado pela API é só área tocável (o IG não desenha o card; quem desenha é o app de quem compartilha), então o worker desenha o card de post (foto de perfil real, @, foto 4:5, rodapé "@ | nome da peça") e encaixa o post tocável em cima, com o dono do post registrado
- feat: **estilo vitrine** (padrão) — fundo laranja do brechó, etiqueta de preço/tamanho na letra da logo (Walter Turncoat) e chamada pra ação ("comente “fila” para garantir a sua!", ou o `texto` do modo; quebra em linhas); `estilo = "original"` copia o card do Insta
- feat: **vídeo de abertura** (`video_intro`, ligado no aleatório) — posta `assets/intro.mp4` ("confiram as peças disponíveis no destaque") antes das peças; usa `moviepy` 2.x
- fix: **peças dos drops do histórico** (scraper sem drop manual, agrupadas pela data do post — igual o app do brechó) agora entram: 78 disponíveis em vez de ~37; último drop considera os dois tipos
- update: leitura dos posts do brechó incremental (60 mais novos a cada 12h; completa até 800 a cada 3 dias ou quando falta peça)
- feat: **dois modos** — `aleatório` (todas as disponíveis) e `drop novo` (só o último drop postado); 10 stories por run e 1–7s entre eles por padrão, tudo configurável no modo
- feat: **ciclo por conta e por modo** — sorteia sem repetir peça até a conta postar todas; recalculado a cada run sobre as disponíveis do momento (drop novo no meio não quebra nada)
- feat: **lote** (`IG_LOTE_CONTAS`) — várias contas numa run, uma de cada vez; brechó lido 1x; conta barrada é pulada e listada no fim
- feat: **apaga o story de peça que vendeu** (stories < 24h que este bot postou na conta)
- feat: **etiqueta modular** (`etiqueta.py`) — regras em ordem (várias ofertas → peça simples → sem preço) sobre uma leitura genérica da descrição/legenda: conjunto/kit/"os dois" em qualquer posição, com ou sem separador; avulso compacto ou uma linha por peça; parte marcada VENDIDO sai e quebra o pacote. Testes em `test_etiqueta.py`
- feat: legendas do brechó (cache 12h em `output/posts_brecho.json`) ligam a peça manual sem `code` ao post pela tag `#p<num>`, dão a descrição pra etiqueta, dão a **foto do story (1ª imagem do post; a do app vira reserva)** e **pulam peça com o post marcado VENDIDO**; foto relativa (`/uploads/…`) vira URL do brechó
- feat: foto 3:4 aparece inteira no card (antes cortava em 4:5); etiqueta nunca sobe pra barra do story
- feat: conta sem permissão de postar (`login_required`) **para o run com mensagem clara**
- feat: worker **story-repost** — posta os últimos posts da conta no story dela, via `instagrapi` (API privada, sem Playwright/Chromium — leve). Dois modos: **repostar drop** (post embutido como card sobre fundo desfocado) e **imagem cheia** (a imagem do post em 9:16), com **texto** e **link** opcionais.
- feat: login por **`sessionid`** (reaproveita a sessão do app, sem senha) + **proxy socks5** (mesmo túnel :1080 dos outros workers).
- feat: **modos configuráveis** (perfis.json, mesmo padrão dos outros): `repost_card`, `quantos_posts`, `texto`, `link`, `delay_post`, `active_hours`.
- feat: **dedup** — cada post só vai pro story uma vez (`output/state-<conta>.json`).
