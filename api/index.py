# api/index.py - VERSÃO FINALÍSSIMA CORRIGIDA COM A ROTA /generate_upload_urls
import os
import threading
import tempfile
import shutil
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from google.cloud import storage

from core.video_processor import VideoProcessor
from core.tiktok_transcription import transcribe_tiktok_video

# --- Configuração ---
BUCKET_NAME = 'dark_storage' # <-- VERIFIQUE SE ESTE É O NOME DO SEU BUCKET
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
            if progress is not None: 
                progress_data[key]['progress'] = progress
                # Também salva no disco para progresso granular
                try:
                    import json
                    progress_file = f"/tmp/progress_{session_id}.json"
                    with open(progress_file, 'w') as f:
                        json.dump({'progress': progress, 'message': message}, f)
                    app.logger.info(f"Progresso salvo no disco: {progress}% - {message}")
                except Exception as e:
                    app.logger.error(f"Erro ao salvar progresso no disco: {e}")
            progress_data[key]['message'] = message
            app.logger.info(f"Progresso atualizado: {progress}% - {message}")
        
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
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    app.logger.info(f"Vídeo criado com sucesso: {output_path} ({file_size} bytes)")
                    progress_data[key]['output_name'] = secure_filename(output_filename)
                    progress_data[key]['temp_dir'] = temp_dir  # Salva o diretório temporário
                    progress_data[key]['output_path'] = output_path  # Salva o caminho completo
                else:
                    app.logger.error(f"Arquivo de vídeo não foi criado: {output_path}")
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
    task_type = request.args.get('type', 'create')
    if not session_id:
        return jsonify({'error': 'session_id é necessário'}), 400
    
    app.logger.info(f"Solicitação de progresso para session_id: {session_id}, type: {task_type}")
    
    # First try to read from disk-based progress (granular progress)
    import json
    progress_file = f"/tmp/progress_{session_id}.json"
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                disk_progress = json.load(f)
                app.logger.info(f"Progresso do disco: {disk_progress}")
                return jsonify(disk_progress)
        except Exception as e:
            app.logger.error(f"Error reading progress file: {e}")
    
    # Fallback to in-memory progress data - try both key formats
    key_standard = f"{session_id}_{task_type}"
    key_alt = f"{session_id}_create" if task_type == 'create' else f"{session_id}_{task_type}"
    
    app.logger.info(f"Tentando chaves: {key_standard}, {key_alt}")
    app.logger.info(f"Chaves disponíveis: {list(progress_data.keys())}")
    
    if key_standard in progress_data:
        result = progress_data[key_standard]
        app.logger.info(f"Progresso encontrado com chave padrão: {result}")
        return jsonify(result)
    elif key_alt in progress_data:
        result = progress_data[key_alt]
        app.logger.info(f"Progresso encontrado com chave alternativa: {result}")
        return jsonify(result)
    else:
        app.logger.warning(f"Nenhum progresso encontrado para session_id: {session_id}")
        return jsonify({'error': 'Sessão não encontrada'}), 404

@app.route('/download/<session_id>', methods=['GET'])
def download_video(session_id):
    try:
        # Tenta as duas chaves possíveis para compatibilidade
        key_create = f'{session_id}_create'
        key_progress = f'progress_{session_id}'
        
        app.logger.info(f"Tentando download para session_id: {session_id}")
        
        # Verifica se temos dados de progresso para esta sessão
        session_data = None
        if key_create in progress_data:
            session_data = progress_data[key_create]
            app.logger.info(f"Dados encontrados com chave create: {key_create}")
        elif key_progress in progress_data:
            session_data = progress_data[key_progress]
            app.logger.info(f"Dados encontrados com chave progress: {key_progress}")
        
        if not session_data:
            app.logger.error(f"Dados de progresso não encontrados para session_id: {session_id}")
            app.logger.error(f"Chaves disponíveis: {list(progress_data.keys())}")
            return jsonify({'error': 'Sessão não encontrada'}), 404
        
        app.logger.info(f"Dados da sessão: {session_data}")
        
        # Tenta usar o caminho completo salvo primeiro
        video_path = None
        if 'output_path' in session_data and os.path.exists(session_data['output_path']):
            video_path = session_data['output_path']
            app.logger.info(f"Usando caminho completo salvo: {video_path}")
        else:
            # Fallback para o método anterior
            temp_dir = session_data.get('temp_dir', os.path.join(tempfile.gettempdir(), session_id))
            app.logger.info(f"Diretório temporário: {temp_dir}")
            
            # Verifica se o diretório temporário existe
            if not os.path.exists(temp_dir):
                app.logger.error(f"Diretório temporário não encontrado: {temp_dir}")
                return jsonify({'error': 'Diretório temporário não encontrado'}), 404
            
            # Tenta obter o nome do arquivo de saída
            output_filename = session_data.get('output_name', 'video.mp4')
            if output_filename:
                potential_path = os.path.join(temp_dir, output_filename)
                if os.path.exists(potential_path):
                    video_path = potential_path
                    app.logger.info(f"Arquivo encontrado: {video_path}")
            
            # Se não encontrou, procura por qualquer arquivo .mp4
            if not video_path:
                app.logger.info("Procurando por arquivos .mp4 no diretório")
                try:
                    files = os.listdir(temp_dir)
                    app.logger.info(f"Arquivos no diretório: {files}")
                    
                    for file in files:
                        if file.endswith('.mp4'):
                            potential_path = os.path.join(temp_dir, file)
                            if os.path.exists(potential_path):
                                video_path = potential_path
                                app.logger.info(f"Arquivo .mp4 encontrado: {video_path}")
                                break
                except OSError as e:
                    app.logger.error(f"Erro ao listar arquivos no diretório {temp_dir}: {e}")
                    return jsonify({'error': 'Erro ao acessar diretório temporário'}), 500
        
        if not video_path:
            app.logger.error("Nenhum arquivo de vídeo encontrado")
            return jsonify({'error': 'Arquivo de vídeo não encontrado'}), 404
        
        # Verifica o tamanho do arquivo
        try:
            file_size = os.path.getsize(video_path)
            app.logger.info(f"Tamanho do arquivo: {file_size} bytes")
            
            if file_size == 0:
                app.logger.error("Arquivo de vídeo está vazio")
                return jsonify({'error': 'Arquivo de vídeo está vazio'}), 404
        except OSError as e:
            app.logger.error(f"Erro ao verificar tamanho do arquivo: {e}")
            return jsonify({'error': 'Erro ao verificar arquivo'}), 500
        
        app.logger.info(f"Enviando arquivo: {video_path}")
        output_filename = session_data.get('output_name', f'video_{session_id}.mp4')
        return send_file(video_path, as_attachment=True, download_name=output_filename)
        
    except Exception as e:
        app.logger.error(f"Erro no download: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/get_transcription/<session_id>')
def get_transcription(session_id):
    result = transcription_results.get(session_id)
    if not result:
        return jsonify({'error': 'Transcrição não encontrada ou ainda em progresso'}), 404
    return jsonify(result)