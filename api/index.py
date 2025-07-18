# api/index.py - VERSÃO FINALÍSSIMA CORRIGIDA COM A ROTA /generate_upload_urls
import os
import threading
import tempfile
import shutil
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, redirect
from werkzeug.utils import secure_filename
from google.cloud import storage
from core.video_processor import VideoProcessor
from core.tiktok_transcription import transcribe_tiktok_video
import datetime

# --- Configuração ---
BUCKET_NAME = 'dark_storage' 
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
app = Flask(__name__, template_folder=TEMPLATE_DIR)
storage_client = storage.Client()

progress_data = {}
transcription_results = {}
video_processor = VideoProcessor()

@app.route('/')
def index():
    return render_template('index.html')

# ==============================================================================
# A ROTA QUE FALTAVA - ADICIONADA DE VOLTA
# ==============================================================================
@app.route('/generate_upload_urls', methods=['POST'])
def generate_upload_urls():
    try:
        data = request.get_json()
        filenames = data.get('filenames', [])
        if not filenames:
            return jsonify({'error': 'Nenhum nome de arquivo foi fornecido.'}), 400
        
        urls = {}
        bucket = storage_client.bucket(BUCKET_NAME)
        
        for filename in filenames:
            # Cria um nome de arquivo único para evitar colisões
            unique_filename = f"uploads/{int(time.time())}_{secure_filename(filename)}"
            blob = bucket.blob(unique_filename)
            
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=900, # 15 minutos
                method="PUT",
            )
            urls[filename] = {'signedUrl': signed_url, 'gcsPath': blob.name}
            
        return jsonify(urls)
    except Exception as e:
        app.logger.error(f"Erro em generate_upload_urls: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/create_video', methods=['POST'])
def create_video():
    try:
        data = request.get_json()
        files_info = data.get('files', []) # Espera uma lista de {'gcsPath': '...', 'type': 'image'/'audio'}
        
        if not files_info:
            return jsonify({'error': 'Nenhuma informação de arquivo recebida.'}), 400

        temp_dir = tempfile.mkdtemp()
        session_id = os.path.basename(temp_dir)
        bucket = storage_client.bucket(BUCKET_NAME)

        image_paths, audio_path = [], None

        # Baixa os arquivos do GCS para o ambiente temporário do Cloud Run
        for file_info in files_info:
            blob = bucket.blob(file_info['gcsPath'])
            destination_path = os.path.join(temp_dir, os.path.basename(file_info['gcsPath']))
            blob.download_to_filename(destination_path)
            if file_info['type'] == 'image':
                image_paths.append(destination_path)
            elif file_info['type'] == 'audio':
                audio_path = destination_path
        
        aspect_ratio = data.get('aspect_ratio', '9:16')
        fps = int(data.get('fps', 30))
        green_screen_duration = float(data.get('green_screen_duration', 5.0))
        output_filename = data.get('output_name', 'output.mp4')
        output_path = os.path.join(temp_dir, secure_filename(output_filename))

        key = f"{session_id}_create"
        progress_data[key] = {'progress': 0, 'message': 'Iniciando criação do vídeo...'}
        
        def progress_callback(message, progress=None):
            """Callback para atualizar o progresso"""
            try:
                # Ensure progress is within valid range
                if progress is not None:
                    progress = max(0, min(100, progress))
                    progress_data[key]['progress'] = progress
                
                progress_data[key]['message'] = message
                progress_data[key]['timestamp'] = time.time()
                
                # Also store with alternative key for compatibility
                progress_data[f"progress_{session_id}"] = progress_data[key].copy()
                
                # Save granular progress to disk
                import json
                progress_file = f"/tmp/progress_{session_id}.json"
                session_file = f"/tmp/session_{session_id}.json"
                
                # Save progress file
                progress_info = {
                    'progress': progress_data[key]['progress'],
                    'message': message,
                    'timestamp': time.time(),
                    'session_id': session_id
                }
                
                with open(progress_file, 'w') as f:
                    json.dump(progress_info, f)
                
                # Save session file with all data
                session_data_to_save = progress_data[key].copy()
                
                # Include additional session info if available
                session_data_to_save.update({
                    'temp_dir': session_data_to_save.get('temp_dir'),
                    'output_path': session_data_to_save.get('output_path'),
                    'created_at': session_data_to_save.get('created_at', time.time())
                })
                
                with open(session_file, 'w') as f:
                    json.dump(session_data_to_save, f)
                
                app.logger.info(f"Progresso atualizado: {progress}% - {message} (Session: {session_id})")
                
            except Exception as e:
                app.logger.error(f"Error updating progress for session {session_id}: {e}")
                import traceback
                app.logger.error(traceback.format_exc())
        
        def create_video_thread():
            try:
                app.logger.info(f"Iniciando criação de vídeo - Session ID: {session_id}")
                app.logger.info(f"Diretório temporário: {temp_dir}")
                app.logger.info(f"Arquivo de saída: {output_path}")
                app.logger.info(f"Imagens: {len(image_paths)} arquivos")
                app.logger.info(f"Áudio: {audio_path}")
                
                video_processor.create_multi_video_with_separators(
                    image_paths=image_paths, audio_path=audio_path, output_path=output_path,
                    aspect_ratio=aspect_ratio, fps=fps, green_screen_duration=green_screen_duration,
                    progress_callback=progress_callback, session_id=session_id
                )
                
                # Verifica se o arquivo foi criado com sucesso
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    file_size = os.path.getsize(output_path)
                    app.logger.info(f"Vídeo criado com sucesso: {output_path} ({file_size} bytes)")
                    
                    # --- NOVO TRECHO: UPLOAD PARA O GCS ---
                    progress_callback("Fazendo upload do vídeo final...", 98)
                    
                    bucket = storage_client.bucket(BUCKET_NAME)
                    # Define um caminho no bucket para o vídeo finalizado
                    final_video_filename = f"outputs/{session_id}_{secure_filename(output_filename)}"
                    blob = bucket.blob(final_video_filename)
                    
                    # Faz o upload do arquivo a partir do disco temporário
                    blob.upload_from_filename(output_path)
                    
                    app.logger.info(f"Vídeo final enviado para o GCS: gs://{BUCKET_NAME}/{final_video_filename}")
                    
                    # Salva o caminho do GCS nos dados da sessão em vez do caminho local
                    progress_data[key]['gcs_path'] = final_video_filename
                    progress_data[key]['output_name'] = secure_filename(output_filename)  # Mantém o nome original
                    # --- FIM DO NOVO TRECHO ---
                else:
                    app.logger.error(f"Arquivo de vídeo não foi criado ou está vazio: {output_path}")
                    progress_data[key]['message'] = 'Erro: Arquivo de vídeo não foi criado'
                    
            except Exception as e:
                import traceback
                error_message = f'Erro na thread: {e}\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                app.logger.error(error_message)
                app.logger.error(f"Diretório temporário no erro: {temp_dir}")
                app.logger.error(f"Arquivos no diretório: {os.listdir(temp_dir) if os.path.exists(temp_dir) else 'Diretório não existe'}")

        thread = threading.Thread(target=create_video_thread)
        thread.start()
        
        return jsonify({'success': True, 'session_id': session_id, 'message': 'Processamento iniciado.'})
    except Exception as e:
        app.logger.error(f"Erro em create_video: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/transcribe_tiktok', methods=['POST'])
def transcribe_tiktok():
    try:
        data = request.get_json()
        url = data.get('url')
        if not url: return jsonify({'error': 'Nenhum link do TikTok fornecido.'}), 400
        
        session_id = os.path.basename(tempfile.mkdtemp())
        key = f"{session_id}_transcribe"
        progress_data[key] = {'progress': 0, 'message': 'Iniciando transcrição...'}
        
        def progress_callback(message, progress=None):
            if progress is not None: progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
        
        def transcribe_thread():
            try:
                result = transcribe_tiktok_video(url, progress_callback=progress_callback)
                transcription_results[session_id] = result
                if result['success']:
                    progress_data[key]['progress'] = 100
                    progress_data[key]['message'] = 'Transcrição completa!'
                else:
                    progress_data[key]['message'] = f"Falha na transcrição: {result.get('error', 'Erro desconhecido')}"
            except Exception as e:
                import traceback
                error_message = f'Erro na thread: {e}\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                app.logger.error(error_message)
        
        thread = threading.Thread(target=transcribe_thread)
        thread.start()
        
        return jsonify({'success': True, 'session_id': session_id, 'message': 'Transcrição iniciada.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/progress')
def get_progress():
    session_id = request.args.get('session_id')
    progress_type = request.args.get('type', 'create')
    
    if not session_id:
        return jsonify({'error': 'session_id é obrigatório'}), 400
    
    app.logger.info(f"Solicitação de progresso para session_id: {session_id}, type: {progress_type}")

    import json, time, os
    progress_dir = "/mnt/data/progress"
    os.makedirs(progress_dir, exist_ok=True)

    # referencia inicial: tenta carregar arquivo granular persistente
    progress_file = os.path.join(progress_dir, f"progress_{session_id}.json")
    try:
        with open(progress_file, 'r') as f:
            file_data = json.load(f)
            app.logger.info(f"Progresso carregado do arquivo granular: {file_data.get('progress', 0)}% - {file_data.get('message', '')}")
            return jsonify({
                'progress': file_data.get('progress', 0),
                'message': file_data.get('message', 'Processando...'),
                'timestamp': file_data.get('timestamp', time.time())
            })
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.debug(f"Arquivo de progresso granular não disponível: {e}")
    # referencia final: fim da tentativa de leitura persistente

    # Fallback: (opcional) ainda tenta o antigo /tmp se necessário
    legacy_session_file = f"/tmp/session_{session_id}.json"
    try:
        with open(legacy_session_file, 'r') as f:
            session_data = json.load(f)
            app.logger.info(f"Progresso carregado do arquivo de sessão: {session_data.get('progress', 0)}% - {session_data.get('message', '')}")
            return jsonify({
                'progress': session_data.get('progress', 0),
                'message': session_data.get('message', 'Processando...'),
                'timestamp': session_data.get('timestamp', time.time())
            })
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.debug(f"Arquivo de sessão não disponível: {e}")

    # Fallback to in-memory data
    keys_to_try = [f"{session_id}_{progress_type}", f"progress_{session_id}", session_id]
    app.logger.debug(f"Tentando chaves na memória: {keys_to_try}")
    app.logger.debug(f"Chaves disponíveis na memória: {list(progress_data.keys())}")
    
    for key in keys_to_try:
        if key in progress_data:
            data = progress_data[key]
            app.logger.info(f"Progresso encontrado na memória com chave {key}: {data.get('progress', 0)}% - {data.get('message', '')}")
            return jsonify({
                'progress': data.get('progress', 0),
                'message': data.get('message', 'Processando...'),
                'timestamp': data.get('timestamp', time.time())
            })

    # Caso nenhuma fonte de progresso encontrada
    app.logger.warning(f"Nenhum progresso encontrado para session_id: {session_id}")
    app.logger.info("Isso pode indicar uma mudança de instância no Cloud Run ou sessão ainda não iniciada")
    
    return jsonify({
        'progress': 0,
        'message': 'Aguardando início do processamento...',
        'timestamp': time.time(),
        'waiting': True
    }), 200


@app.route('/download/<session_id>', methods=['GET'])
def download_video(session_id):
    try:
        app.logger.info(f"Requisição de download para a sessão: {session_id}")
        
        # Para um ambiente stateless, a melhor abordagem é ter um "arquivo de status" no GCS
        # ou usar um banco de dados como Firestore/Redis.
        # Por simplicidade, vamos manter a lógica de `progress_data` em memória,
        # mas a solução robusta envolveria consultar uma fonte de dados externa.
        
        key_create = f'{session_id}_create'
        session_data = progress_data.get(key_create)
        
        if not session_data:
            app.logger.error(f"Dados da sessão não encontrados na memória para {session_id}")
            # AQUI VOCÊ PODERIA ADICIONAR UMA LÓGICA DE FALLBACK PARA LER UM ARQUIVO DE STATUS DO GCS
            return jsonify({'error': 'Sessão não encontrada ou a instância foi reiniciada. Tente novamente.'}), 404

        gcs_path = session_data.get('gcs_path')
        if not gcs_path:
            app.logger.error(f"Caminho do GCS não encontrado nos dados da sessão para {session_id}")
            return jsonify({'error': 'O arquivo final ainda não está pronto ou houve um erro no upload.'}), 404

        # Gera uma URL assinada para o download
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)

        if not blob.exists():
            app.logger.error(f"O arquivo {gcs_path} não existe no GCS.")
            return jsonify({'error': 'Arquivo não encontrado no armazenamento.'}), 404

        # A URL expira em 10 minutos
        expiration_time = datetime.timedelta(minutes=10)
        
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=expiration_time,
            method="GET",
            response_disposition=f"attachment; filename={session_data.get('output_name')}"
        )
        
        app.logger.info(f"Redirecionando usuário para a URL assinada de download.")
        # Redireciona o navegador do usuário para a URL de download direto do GCS
        return redirect(signed_url, code=302)

    except Exception as e:
        app.logger.error(f"Erro no download: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Erro interno do servidor ao tentar gerar o link de download.'}), 500

@app.route('/get_transcription/<session_id>')
def get_transcription(session_id):
    result = transcription_results.get(session_id)
    if not result:
        return jsonify({'error': 'Transcrição não encontrada ou ainda em progresso'}), 404
    return jsonify(result)