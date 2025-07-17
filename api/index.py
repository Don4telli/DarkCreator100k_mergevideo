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
BUCKET_NAME = 'darkcreator-uploads-12345' # <-- VERIFIQUE SE ESTE É O NOME DO SEU BUCKET
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
            if progress is not None: progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
        
        def create_video_thread():
            try:
                video_processor.create_multi_video_with_separators(
                    image_paths=image_paths, audio_path=audio_path, output_path=output_path,
                    aspect_ratio=aspect_ratio, fps=fps, green_screen_duration=green_screen_duration,
                    progress_callback=progress_callback
                )
                progress_data[key]['output_name'] = secure_filename(output_filename) # Salva o nome para o download
            except Exception as e:
                import traceback
                error_message = f'Erro na thread: {e}\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                app.logger.error(error_message)

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
    task_type = request.args.get('type')
    if not session_id or not task_type:
        return jsonify({'error': 'session_id e type são necessários'}), 400
    key = f"{session_id}_{task_type}"
    return jsonify(progress_data.get(key, {'progress': 0, 'message': 'Aguardando...'}))

@app.route('/download/<session_id>')
def download_video(session_id):
    try:
        temp_dir = os.path.join(tempfile.gettempdir(), session_id)
        
        # Pega o nome do arquivo que foi salvo no progresso
        progress_key = f"{session_id}_create"
        output_filename = progress_data.get(progress_key, {}).get('output_name', 'video.mp4')
        
        output_path = os.path.join(temp_dir, output_filename)
        
        if not os.path.exists(output_path):
            # Tenta encontrar qualquer .mp4 como fallback
            mp4_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
            if not mp4_files:
                return "Arquivo de vídeo não encontrado.", 404
            output_path = os.path.join(temp_dir, mp4_files[0])
            
        return send_file(output_path, as_attachment=True)
    except Exception as e:
        app.logger.error(f"Erro no download: {e}")
        return str(e), 500

@app.route('/get_transcription/<session_id>')
def get_transcription(session_id):
    result = transcription_results.get(session_id)
    if not result:
        return jsonify({'error': 'Transcrição não encontrada ou ainda em progresso'}), 404
    return jsonify(result)