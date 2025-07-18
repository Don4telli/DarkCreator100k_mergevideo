# api/index.py - VERSÃO CORRIGIDA COM PERSISTÊNCIA NO GCS
import os
import threading
import tempfile
import shutil
import time
import json
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

# --- FUNÇÕES AUXILIARES PARA PERSISTÊNCIA ---
def save_session_metadata(session_id, metadata):
    """Salva metadados da sessão no GCS"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"sessions/{session_id}_metadata.json")
        blob.upload_from_string(json.dumps(metadata))
        app.logger.info(f"Metadados da sessão salvos no GCS: {session_id}")
    except Exception as e:
        app.logger.error(f"Erro ao salvar metadados da sessão {session_id}: {e}")

def load_session_metadata(session_id):
    """Carrega metadados da sessão do GCS"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"sessions/{session_id}_metadata.json")
        if blob.exists():
            metadata = json.loads(blob.download_as_text())
            app.logger.info(f"Metadados da sessão carregados do GCS: {session_id}")
            return metadata
        else:
            app.logger.warning(f"Arquivo de metadados não encontrado no GCS: {session_id}")
            return None
    except Exception as e:
        app.logger.error(f"Erro ao carregar metadados da sessão {session_id}: {e}")
        return None

def save_progress_to_gcs(session_id, progress_info):
    """Salva progresso no GCS"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"progress/{session_id}_progress.json")
        blob.upload_from_string(json.dumps(progress_info))
    except Exception as e:
        app.logger.error(f"Erro ao salvar progresso no GCS {session_id}: {e}")

def load_progress_from_gcs(session_id):
    """Carrega progresso do GCS"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"progress/{session_id}_progress.json")
        if blob.exists():
            return json.loads(blob.download_as_text())
        return None
    except Exception as e:
        app.logger.error(f"Erro ao carregar progresso do GCS {session_id}: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

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
        initial_progress = {
            'progress': 0, 
            'message': 'Iniciando criação do vídeo...',
            'timestamp': time.time(),
            'session_id': session_id,
            'status': 'processing'
        }
        progress_data[key] = initial_progress
        
        # Salva progresso inicial no GCS
        save_progress_to_gcs(session_id, initial_progress)
        
        def progress_callback(message, progress=None):
            """Callback para atualizar o progresso"""
            try:
                # Ensure progress is within valid range
                if progress is not None:
                    progress = max(0, min(100, progress))
                    progress_data[key]['progress'] = progress
                
                progress_data[key]['message'] = message
                progress_data[key]['timestamp'] = time.time()
                
                # Salva no GCS também
                progress_info = {
                    'progress': progress_data[key]['progress'],
                    'message': message,
                    'timestamp': time.time(),
                    'session_id': session_id,
                    'status': 'processing' if progress < 100 else 'completed'
                }
                save_progress_to_gcs(session_id, progress_info)
                
                # Also store with alternative key for compatibility
                progress_data[f"progress_{session_id}"] = progress_data[key].copy()
                
                # Save granular progress to disk (mantém para fallback local)
                progress_file = f"/tmp/progress_{session_id}.json"
                session_file = f"/tmp/session_{session_id}.json"
                
                with open(progress_file, 'w') as f:
                    json.dump(progress_info, f)
                
                # Save session file with all data
                session_data_to_save = progress_data[key].copy()
                session_data_to_save.update({
                    'temp_dir': temp_dir,
                    'output_path': output_path,
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
                progress_callback('Sessão iniciada...', 1)
                app.logger.info(f"Iniciando criação de vídeo - Session ID: {session_id}")
                app.logger.info(f"Diretório temporário: {temp_dir}")
                app.logger.info(f"Arquivo de saída: {output_path}")
                app.logger.info(f"Imagens: {len(image_paths)} arquivos")
                app.logger.info(f"Áudio: {audio_path}")
                
                progress_callback('Inicializando variáveis...', 5)
                progress_callback('Baixando arquivos do bucket...', 10)
                progress_callback('Convertendo imagens para vídeo base...', 25)
                
                video_processor.create_multi_video_with_separators(
                    image_paths=image_paths, audio_path=audio_path, output_path=output_path,
                    aspect_ratio=aspect_ratio, fps=fps, green_screen_duration=green_screen_duration,
                    progress_callback=progress_callback, session_id=session_id
                )
                
                progress_callback('Salvando arquivo final...', 90)
                
                # Verifica se o arquivo foi criado com sucesso
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    file_size = os.path.getsize(output_path)
                    app.logger.info(f"Vídeo criado com sucesso: {output_path} ({file_size} bytes)")
                    
                    progress_callback("Fazendo upload do vídeo final...", 95)
                    
                    bucket = storage_client.bucket(BUCKET_NAME)
                    final_video_filename = f"outputs/{session_id}_{secure_filename(output_filename)}"
                    blob = bucket.blob(final_video_filename)
                    
                    # Faz o upload do arquivo a partir do disco temporário
                    blob.upload_from_filename(output_path)
                    
                    app.logger.info(f"Vídeo final enviado para o GCS: gs://{BUCKET_NAME}/{final_video_filename}")
                    
                    # Salva metadados da sessão no GCS
                    session_metadata = {
                        'session_id': session_id,
                        'gcs_path': final_video_filename,
                        'output_name': secure_filename(output_filename),
                        'created_at': time.time(),
                        'file_size': file_size,
                        'status': 'completed'
                    }
                    save_session_metadata(session_id, session_metadata)
                    
                    # Também salva na memória para compatibilidade
                    progress_data[key]['gcs_path'] = final_video_filename
                    progress_data[key]['output_name'] = secure_filename(output_filename)
                    progress_data[key]['status'] = 'completed'
                    
                    progress_callback('🎉 Finalizado! Baixe seu vídeo.', 100)
                    
                    # Cleanup do diretório temporário
                    try:
                        shutil.rmtree(temp_dir)
                        app.logger.info(f"Diretório temporário removido: {temp_dir}")
                    except Exception as e:
                        app.logger.warning(f"Erro ao remover diretório temporário: {e}")
                        
                else:
                    app.logger.error(f"Arquivo de vídeo não foi criado ou está vazio: {output_path}")
                    error_msg = 'Erro: Arquivo de vídeo não foi criado'
                    progress_data[key]['message'] = error_msg
                    progress_data[key]['status'] = 'error'
                    
                    # Salva erro no GCS
                    error_info = {
                        'progress': 0,
                        'message': error_msg,
                        'timestamp': time.time(),
                        'session_id': session_id,
                        'status': 'error'
                    }
                    save_progress_to_gcs(session_id, error_info)
                    
            except Exception as e:
                import traceback
                error_message = f'Erro na thread: {e}\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                progress_data[key]['status'] = 'error'
                app.logger.error(error_message)
                
                # Salva erro no GCS
                error_info = {
                    'progress': 0,
                    'message': error_message,
                    'timestamp': time.time(),
                    'session_id': session_id,
                    'status': 'error'
                }
                save_progress_to_gcs(session_id, error_info)

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
        initial_progress = {
            'progress': 0, 
            'message': 'Iniciando transcrição...',
            'timestamp': time.time(),
            'session_id': session_id,
            'status': 'processing'
        }
        progress_data[key] = initial_progress
        save_progress_to_gcs(session_id, initial_progress)
        
        def progress_callback(message, progress=None):
            if progress is not None: 
                progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
            progress_data[key]['timestamp'] = time.time()
            
            # Salva no GCS também
            progress_info = {
                'progress': progress_data[key]['progress'],
                'message': message,
                'timestamp': time.time(),
                'session_id': session_id,
                'status': 'processing' if progress < 100 else 'completed'
            }
            save_progress_to_gcs(session_id, progress_info)
        
        def transcribe_thread():
            try:
                result = transcribe_tiktok_video(url, progress_callback=progress_callback)
                transcription_results[session_id] = result
                
                # Salva resultado no GCS
                result_metadata = {
                    'session_id': session_id,
                    'result': result,
                    'created_at': time.time(),
                    'status': 'completed' if result['success'] else 'error'
                }
                save_session_metadata(session_id, result_metadata)
                
                if result['success']:
                    progress_data[key]['progress'] = 100
                    progress_data[key]['message'] = 'Transcrição completa!'
                    progress_data[key]['status'] = 'completed'
                else:
                    error_msg = f"Falha na transcrição: {result.get('error', 'Erro desconhecido')}"
                    progress_data[key]['message'] = error_msg
                    progress_data[key]['status'] = 'error'
                    
                # Salva status final no GCS
                final_progress = {
                    'progress': progress_data[key]['progress'],
                    'message': progress_data[key]['message'],
                    'timestamp': time.time(),
                    'session_id': session_id,
                    'status': progress_data[key]['status']
                }
                save_progress_to_gcs(session_id, final_progress)
                
            except Exception as e:
                import traceback
                error_message = f'Erro na thread: {e}\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                progress_data[key]['status'] = 'error'
                app.logger.error(error_message)
                
                # Salva erro no GCS
                error_info = {
                    'progress': 0,
                    'message': error_message,
                    'timestamp': time.time(),
                    'session_id': session_id,
                    'status': 'error'
                }
                save_progress_to_gcs(session_id, error_info)
        
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

    # 1. Primeiro tenta carregar do GCS
    progress_from_gcs = load_progress_from_gcs(session_id)
    if progress_from_gcs:
        app.logger.info(f"Progresso carregado do GCS: {progress_from_gcs.get('progress', 0)}% - {progress_from_gcs.get('message', '')}")
        return jsonify({
            'progress': progress_from_gcs.get('progress', 0),
            'message': progress_from_gcs.get('message', 'Processando...'),
            'timestamp': progress_from_gcs.get('timestamp', time.time()),
            'status': progress_from_gcs.get('status', 'processing')
        })

    # 2. Fallback para arquivo local
    progress_file = f"/tmp/progress_{session_id}.json"
    try:
        with open(progress_file, 'r') as f:
            file_data = json.load(f)
            app.logger.info(f"Progresso carregado do arquivo local: {file_data.get('progress', 0)}% - {file_data.get('message', '')}")
            return jsonify({
                'progress': file_data.get('progress', 0),
                'message': file_data.get('message', 'Processando...'),
                'timestamp': file_data.get('timestamp', time.time()),
                'status': file_data.get('status', 'processing')
            })
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.debug(f"Arquivo de progresso local não disponível: {e}")

    # 3. Fallback para memória
    keys_to_try = [f"{session_id}_{progress_type}", f"progress_{session_id}", session_id]
    app.logger.debug(f"Tentando chaves na memória: {keys_to_try}")
    
    for key in keys_to_try:
        if key in progress_data:
            data = progress_data[key]
            app.logger.info(f"Progresso encontrado na memória com chave {key}: {data.get('progress', 0)}% - {data.get('message', '')}")
            return jsonify({
                'progress': data.get('progress', 0),
                'message': data.get('message', 'Processando...'),
                'timestamp': data.get('timestamp', time.time()),
                'status': data.get('status', 'processing')
            })

    # 4. Caso nenhuma fonte de progresso encontrada
    app.logger.warning(f"Nenhum progresso encontrado para session_id: {session_id}")
    
    return jsonify({
        'progress': 0,
        'message': 'Aguardando início do processamento...',
        'timestamp': time.time(),
        'status': 'waiting'
    }), 200

@app.route('/download/<session_id>', methods=['GET'])
def download_video(session_id):
    try:
        app.logger.info(f"Requisição de download para a sessão: {session_id}")
        
        # 1. Primeiro tenta carregar metadados do GCS
        session_metadata = load_session_metadata(session_id)
        if session_metadata:
            app.logger.info(f"Metadados carregados do GCS para sessão: {session_id}")
            gcs_path = session_metadata.get('gcs_path')
            output_name = session_metadata.get('output_name', 'output.mp4')
            
            if gcs_path:
                # Verifica se o arquivo existe no GCS
                bucket = storage_client.bucket(BUCKET_NAME)
                blob = bucket.blob(gcs_path)
                
                if blob.exists():
                    app.logger.info(f"Arquivo encontrado no GCS: {gcs_path}")
                    # Gera URL assinada para download
                    expiration_time = datetime.timedelta(minutes=15)
                    signed_url = blob.generate_signed_url(
                        version="v4",
                        expiration=expiration_time,
                        method="GET",
                        response_disposition=f"attachment; filename={output_name}"
                    )
                    
                    app.logger.info(f"Redirecionando para download: {output_name}")
                    return redirect(signed_url, code=302)
                else:
                    app.logger.error(f"Arquivo não encontrado no GCS: {gcs_path}")
                    return jsonify({'error': 'Arquivo não encontrado no armazenamento.'}), 404
            else:
                app.logger.error(f"Caminho do GCS não encontrado nos metadados para {session_id}")
                return jsonify({'error': 'Informações do arquivo não encontradas.'}), 404
        
        # 2. Fallback para dados em memória
        key_create = f'{session_id}_create'
        session_data = progress_data.get(key_create)
        
        if session_data:
            app.logger.info(f"Dados da sessão encontrados na memória: {session_id}")
            gcs_path = session_data.get('gcs_path')
            output_name = session_data.get('output_name', 'output.mp4')
            
            if gcs_path:
                bucket = storage_client.bucket(BUCKET_NAME)
                blob = bucket.blob(gcs_path)
                
                if blob.exists():
                    expiration_time = datetime.timedelta(minutes=15)
                    signed_url = blob.generate_signed_url(
                        version="v4",
                        expiration=expiration_time,
                        method="GET",
                        response_disposition=f"attachment; filename={output_name}"
                    )
                    
                    return redirect(signed_url, code=302)
                else:
                    return jsonify({'error': 'Arquivo não encontrado no armazenamento.'}), 404
            else:
                return jsonify({'error': 'Arquivo ainda não está pronto.'}), 404
        
        # 3. Fallback para arquivo local
        try:
            session_file = f"/tmp/session_{session_id}.json"
            with open(session_file, 'r') as f:
                local_session_data = json.load(f)
                app.logger.info(f"Dados da sessão carregados do arquivo local: {session_id}")
                
                gcs_path = local_session_data.get('gcs_path')
                output_name = local_session_data.get('output_name', 'output.mp4')
                
                if gcs_path:
                    bucket = storage_client.bucket(BUCKET_NAME)
                    blob = bucket.blob(gcs_path)
                    
                    if blob.exists():
                        expiration_time = datetime.timedelta(minutes=15)
                        signed_url = blob.generate_signed_url(
                            version="v4",
                            expiration=expiration_time,
                            method="GET",
                            response_disposition=f"attachment; filename={output_name}"
                        )
                        
                        return redirect(signed_url, code=302)
                    else:
                        return jsonify({'error': 'Arquivo não encontrado no armazenamento.'}), 404
                else:
                    return jsonify({'error': 'Arquivo ainda não está pronto.'}), 404
                    
        except (FileNotFoundError, json.JSONDecodeError):
            app.logger.warning(f"Arquivo de sessão local não encontrado: {session_id}")
        
        # 4. Nenhuma fonte de dados encontrada
        app.logger.error(f"Nenhuma informação de sessão encontrada para {session_id}")
        return jsonify({
            'error': 'Sessão não encontrada. Isso pode ter ocorrido devido a:\n' +
                    '• Sessão expirada\n' +
                    '• Processamento ainda em andamento\n' +
                    '• Erro durante o processamento\n\n' +
                    'Tente verificar o status do processamento primeiro.'
        }), 404

    except Exception as e:
        app.logger.error(f"Erro no download: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Erro interno do servidor ao tentar gerar o link de download.'}), 500

@app.route('/get_transcription/<session_id>')
def get_transcription(session_id):
    # 1. Primeiro tenta carregar da memória
    result = transcription_results.get(session_id)
    if result:
        return jsonify(result)
    
    # 2. Fallback para metadados do GCS
    session_metadata = load_session_metadata(session_id)
    if session_metadata and 'result' in session_metadata:
        app.logger.info(f"Transcrição carregada do GCS para sessão: {session_id}")
        return jsonify(session_metadata['result'])
    
    # 3. Não encontrado
    return jsonify({'error': 'Transcrição não encontrada ou ainda em progresso'}), 404

# Rota adicional para limpar sessões antigas (opcional)
@app.route('/cleanup_old_sessions', methods=['POST'])
def cleanup_old_sessions():
    """Remove sessões antigas do GCS (mais de 24 horas)"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        current_time = time.time()
        cleanup_threshold = 24 * 60 * 60  # 24 horas em segundos
        
        deleted_count = 0
        
        # Limpa arquivos de sessão
        for blob in bucket.list_blobs(prefix='sessions/'):
            try:
                # Extrai timestamp do nome do arquivo ou usa created time
                blob_age = current_time - blob.time_created.timestamp()
                
                if blob_age > cleanup_threshold:
                    blob.delete()
                    deleted_count += 1
                    app.logger.info(f"Sessão antiga removida: {blob.name}")
                    
            except Exception as e:
                app.logger.error(f"Erro ao processar blob {blob.name}: {e}")
        
        # Limpa arquivos de progresso
        for blob in bucket.list_blobs(prefix='progress/'):
            try:
                blob_age = current_time - blob.time_created.timestamp()
                
                if blob_age > cleanup_threshold:
                    blob.delete()
                    deleted_count += 1
                    app.logger.info(f"Progresso antigo removido: {blob.name}")
                    
            except Exception as e:
                app.logger.error(f"Erro ao processar blob {blob.name}: {e}")
        
        return jsonify({
            'success': True, 
            'message': f'{deleted_count} arquivos antigos removidos',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        app.logger.error(f"Erro na limpeza de sessões antigas: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)