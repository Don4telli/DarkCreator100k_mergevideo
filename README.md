# DarkCreator100k - Merge Video

Aplicação Flask para criação de vídeos a partir de imagens e áudio, otimizada para Google Cloud Run.

## Funcionalidades

- Upload de múltiplas imagens (JPG, PNG, GIF, BMP, WEBP)
- Upload de arquivo de áudio (MP3, WAV, AAC, FLAC, OGG, M4A)
- Processamento automático com FFmpeg
- Agrupamento de imagens por prefixo
- Inserção de tela verde entre grupos
- Download automático do vídeo final

## Arquitetura

- **Frontend**: HTML/CSS/JavaScript responsivo
- **Backend**: Flask com processamento FFmpeg
- **Storage**: Google Cloud Storage para arquivos
- **Deploy**: Google Cloud Run com Docker

## Deploy no Google Cloud Run

### Pré-requisitos

1. Conta no Google Cloud Platform
2. Projeto criado no GCP
3. Cloud Build API habilitada
4. Cloud Run API habilitada
5. Cloud Storage API habilitada
6. Bucket do Cloud Storage criado: `darkcreator100k-mergevideo`

### Comandos de Deploy

```bash
# 1. Configurar o projeto
gcloud config set project SEU_PROJECT_ID

# 2. Habilitar APIs necessárias
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable storage.googleapis.com

# 3. Criar bucket (se não existir)
gsutil mb gs://darkcreator100k-mergevideo

# 4. Fazer deploy
gcloud builds submit --config cloudbuild.yaml
```

### Configurações do Cloud Run

- **Timeout**: 3600 segundos (1 hora)
- **Memória**: 4Gi
- **CPU**: 2 vCPUs
- **Concorrência**: 1 (para evitar conflitos no processamento)
- **Instâncias máximas**: 10

## Estrutura do Projeto

```
├── app.py                 # Aplicação Flask principal
├── core/
│   └── ffmpeg_processor.py # Processamento de vídeo
├── templates/
│   └── index.html         # Interface web
├── static/
│   └── upload_progress.js # Scripts auxiliares
├── Dockerfile             # Configuração Docker
├── cloudbuild.yaml        # Configuração Cloud Build
├── gunicorn.conf.py       # Configuração Gunicorn
├── requirements.txt       # Dependências Python
└── README.md             # Este arquivo
```

## Solução do Erro 405

O erro 405 Method Not Allowed foi resolvido através das seguintes mudanças:

1. **Mudança na resposta do endpoint `/create_video`**:
   - Antes: Retornava arquivo diretamente com `send_file()`
   - Depois: Faz upload para Cloud Storage e retorna URL de download

2. **Configurações otimizadas do Cloud Run**:
   - Timeout aumentado para 1 hora
   - Memória aumentada para 4Gi
   - Concorrência limitada a 1 instância

3. **Configuração do Gunicorn**:
   - Worker único para evitar conflitos
   - Timeout de 1 hora para processamento
   - Logs detalhados para debug

## Monitoramento

- Endpoint de health check: `/health`
- Logs detalhados em todas as operações
- Tratamento de erros com mensagens específicas

## Limitações

- Tamanho máximo de upload: 512MB
- Tempo máximo de processamento: 1 hora
- Formatos suportados: conforme especificado nas funcionalidades