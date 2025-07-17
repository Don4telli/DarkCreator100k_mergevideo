# DarkCreator100k_mergevideo

## Descrição
Este projeto é uma aplicação para transcrição de vídeos do TikTok e criação de vídeos a partir de imagens e áudio, deployada no Google Cloud Run.

## Como Gerar o Arquivo cookies.txt para Autenticação no TikTok
Para baixar vídeos do TikTok que requerem login, você precisa fornecer um arquivo `cookies.txt` extraído do seu navegador. Aqui estão as instruções:

### Método 1: Usando Extensão de Navegador
1. Instale uma extensão como "Get cookies.txt LOCALLY" no Chrome ou Firefox.
2. Acesse o TikTok no navegador e faça login na sua conta.
3. Use a extensão para exportar os cookies do site tiktok.com para um arquivo `cookies.txt`.
4. Faça upload desse arquivo na interface da aplicação ou coloque-o em `/app/cookies.txt` no ambiente de deploy.

### Método 2: Usando yt-dlp com --cookies-from-browser
1. Instale yt-dlp localmente.
2. Execute: `yt-dlp --cookies-from-browser chrome --dump-user-agent` (substitua 'chrome' pelo seu navegador).
3. Isso gerará os cookies; salve-os em `cookies.txt`.

Certifique-se de que o arquivo esteja no formato Netscape cookies.

## Uso
- Acesse o endpoint /transcribe_tiktok com URL do TikTok e opcionalmente upload de cookies.txt.
- O download só será tentado se o arquivo cookies.txt estiver disponível.

## Dependências
Veja `requirements.txt` para a lista de pacotes necessários.