# 📥 Setup do Download Múltiplo de Vídeos TikTok

## 🎯 Visão Geral

Esta funcionalidade permite baixar múltiplos vídeos do TikTok simultaneamente, contornando a limitação de 32MB do Google Cloud Run através do uso do Google Cloud Storage para armazenar os arquivos.

## 🔧 Configuração Necessária

### 1. Google Cloud Storage

Antes de fazer o deploy, você precisa configurar o Google Cloud Storage:

```bash
# 1. Criar um bucket no Google Cloud Storage
gsutil mb gs://seu-bucket-name

# 2. Configurar permissões (substitua PROJECT_ID pelo seu ID do projeto)
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
    --role="roles/storage.admin"

# 3. Tornar o bucket público para leitura (opcional, para URLs diretas)
gsutil iam ch allUsers:objectViewer gs://seu-bucket-name
```

### 2. Variáveis de Ambiente

Adicione as seguintes variáveis de ambiente ao seu deploy do Cloud Run:

```bash
# Deploy com configurações otimizadas
gcloud run deploy dark-creator-video-app \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --concurrency 10 \
  --max-instances 5 \
  --set-env-vars="GCS_BUCKET=seu-bucket-name,YT_DLP_CACHE_DIR=/tmp/yt-dlp-cache,TMPDIR=/tmp"
```

### 3. Cookies do TikTok (Opcional)

Para melhor compatibilidade com vídeos que exigem autenticação:

1. Exporte os cookies do seu navegador para o TikTok
2. Salve como `/app/cookies.txt` no container
3. Ou adicione via volume mount no Cloud Run

## 🚀 Como Usar

### Interface Web

1. Acesse `/multi_download` na sua aplicação
2. Adicione URLs do TikTok (até 20 por vez)
3. Configure o número de downloads simultâneos (1-5)
4. Clique em "Iniciar Download"
5. Acompanhe o progresso em tempo real
6. Baixe os arquivos através dos links gerados

### API Endpoints

#### Iniciar Download Múltiplo
```bash
POST /download_multiple_tiktoks
Content-Type: application/json

{
  "urls": [
    "https://www.tiktok.com/@user/video/123",
    "https://www.tiktok.com/@user/video/456"
  ],
  "max_workers": 3,
  "session_id": "optional-custom-id"
}
```

#### Verificar Progresso
```bash
GET /multi_download_progress/{session_id}
```

#### Obter Resultados
```bash
GET /multi_download_result/{session_id}
```

#### Limpar Sessão
```bash
DELETE /cleanup_session/{session_id}?keep_storage=true
```

## 📊 Recursos

### ✅ Funcionalidades Implementadas

- **Downloads Concorrentes**: Até 5 downloads simultâneos
- **Progresso em Tempo Real**: Acompanhamento detalhado do progresso
- **Armazenamento em Nuvem**: Arquivos salvos no Google Cloud Storage
- **URLs Assinadas**: Links seguros com expiração de 24 horas
- **Tratamento de Erros**: Mensagens detalhadas para diferentes tipos de falha
- **Interface Moderna**: UI responsiva e intuitiva
- **Limpeza Automática**: Gerenciamento de arquivos temporários
- **Transcrição Incluída**: Texto extraído dos vídeos quando disponível

### 🎛️ Configurações Disponíveis

- **max_workers**: 1-5 downloads simultâneos (padrão: 3)
- **session_id**: ID personalizado da sessão (opcional)
- **keep_storage**: Manter arquivos no storage após limpeza (padrão: true)

## 🔍 Monitoramento e Logs

### Logs Importantes

```bash
# Verificar logs do Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=dark-creator-video-app" --limit 50 --format json

# Filtrar logs específicos do multi-download
gcloud logging read "resource.type=cloud_run_revision AND textPayload:multi-download" --limit 20
```

### Métricas de Performance

- **Tempo médio por download**: ~30-60 segundos por vídeo
- **Limite de URLs**: 20 URLs por sessão
- **Timeout**: 5 minutos por download individual
- **Memória recomendada**: 2Gi para downloads simultâneos
- **CPU recomendada**: 2 CPUs para melhor performance

## 🛠️ Troubleshooting

### Problemas Comuns

1. **Erro de Permissão no Storage**
   ```bash
   # Verificar permissões
   gcloud projects get-iam-policy PROJECT_ID
   
   # Adicionar permissão se necessário
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
     --role="roles/storage.admin"
   ```

2. **Timeout nos Downloads**
   - Reduzir `max_workers` para 1-2
   - Verificar se o vídeo está disponível publicamente
   - Adicionar cookies de autenticação

3. **Erro de Memória**
   - Aumentar memória para 4Gi
   - Reduzir downloads simultâneos
   - Verificar logs de uso de memória

4. **Vídeos Privados/Protegidos**
   - Adicionar arquivo de cookies válido
   - Verificar se a URL está correta
   - Alguns vídeos podem exigir login

### Comandos de Diagnóstico

```bash
# Testar conectividade com o bucket
gsutil ls gs://seu-bucket-name

# Verificar espaço em disco no Cloud Run
df -h /tmp

# Testar yt-dlp manualmente
yt-dlp --version
yt-dlp --extract-audio --audio-format mp3 "URL_DO_TIKTOK"
```

## 🔄 Atualizações Futuras

### Melhorias Planejadas

- [ ] Suporte a playlists do TikTok
- [ ] Download de vídeos de outros platforms (YouTube, Instagram)
- [ ] Compressão automática de vídeos
- [ ] Integração com CDN para downloads mais rápidos
- [ ] Dashboard de analytics de downloads
- [ ] API rate limiting
- [ ] Webhook notifications

## 📞 Suporte

Para problemas ou dúvidas:

1. Verifique os logs do Cloud Run
2. Consulte a seção de troubleshooting
3. Teste com URLs públicas primeiro
4. Verifique as configurações do Google Cloud Storage

---

**Nota**: Esta funcionalidade foi desenvolvida para contornar as limitações do Cloud Run e melhorar a experiência de download de múltiplos vídeos do TikTok. Use com responsabilidade e respeite os termos de serviço do TikTok.