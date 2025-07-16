import os
import threading
import tempfile
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import google.cloud.logging as cloud_logging
from google.cloud import storage
import traceback

# As importações agora funcionam diretamente graças ao PYTHONPATH no Dockerfile.
from core.video_processor import VideoProcessor
from core.tiktok_transcription import transcribe_tiktok_video
# StorageManager removido - usando upload direto para GCS

# Inicialização do Flask, apontando para a pasta de templates na raiz.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
print("=== APP SUBIU!===")
logging.info("=== LOGGING OK!===")

app = Flask(__name__, template_folder=TEMPLATE_DIR)

# Configuração do Cloud Logging
logging_client = cloud_logging.Client()
logging_client.setup_logging()

# Inicializa o cliente do GCS
storage_client = storage.Client()
bucket_name = os.environ.get('GCS_BUCKET', 'dark_storage')  # Defina GCS_BUCKET no ambiente

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# Variáveis globais para rastrear o progresso
progress_data = {}
transcription_results = {}
video_processor = VideoProcessor()

# Inicializar processador de vídeo
# StorageManager removido - usando upload direto para GCS

@app.route('/')
def index():
    print("Passei aqui na /")
    logging.info("Passei aqui também na /")
    return render_template('index.html')

# Removido endpoint de multi download

@app.route('/create_video', methods=['POST'])
def create_video():
    app.logger.info('[INFO] POST /create_video iniciado')
    try:
        temp_dir = tempfile.mkdtemp(dir='/tmp')
        session_id = os.path.basename(temp_dir)
        
        image_files = request.files.getlist('images')
        image_paths = []
        for i, file in enumerate(image_files):
            if file and file.filename:
                filename = secure_filename(f"image_{i:03d}_{file.filename}")
                filepath = os.path.join(temp_dir, filename)
                file.save(filepath)
                app.logger.info(f'[INFO] Arquivo de imagem salvo temporariamente em {filepath}')
                image_paths.append(filepath)

        if not image_paths:
            return jsonify({'error': 'Nenhuma imagem foi enviada.'}), 400

        audio_path = None
        if 'audio' in request.files and request.files['audio'].filename:
            audio_file = request.files['audio']
            audio_filename = secure_filename(f"audio_{audio_file.filename}")
            audio_path = os.path.join(temp_dir, audio_filename)
            audio_file.save(audio_path)
            app.logger.info(f'[INFO] Arquivo de áudio salvo temporariamente em {audio_path}')

        num_images = len(image_paths)
        num_audio = 1 if audio_path else 0
        app.logger.info(f'[INFO] {num_images} imagens e {num_audio} áudio recebidos')

        aspect_ratio = request.form.get('aspect_ratio', '9:16')
        fps = int(request.form.get('fps', 30))
        green_screen_duration = float(request.form.get('green_screen_duration', 5.0))
        output_filename = request.form.get('output_name', 'output.mp4')
        output_path = os.path.join(temp_dir, secure_filename(output_filename))
        
        key = f"{session_id}_create"
        progress_data[key] = {'progress': 0, 'message': 'Iniciando criação do vídeo...'}

        def progress_callback(message, progress=None):
            if progress is not None: progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
        
        def create_video_thread():
            try:
                app.logger.info('[INFO] Processando vídeo com moviepy...')
                video_processor.create_multi_video_with_separators(
                    image_paths=image_paths, audio_path=audio_path, output_path=output_path,
                    aspect_ratio=aspect_ratio, fps=fps, green_screen_duration=green_screen_duration,
                    progress_callback=progress_callback
                )
                app.logger.info(f'[INFO] Vídeo criado em {output_path}')

                # Upload do vídeo final para GCS
                progress_callback('Fazendo upload do vídeo para o storage...', 95)
                blob_name = f'videos/{session_id}/{output_filename}'
                
                try:
                    # Upload direto para GCS
                    bucket = storage_client.bucket(bucket_name)
                    blob = bucket.blob(blob_name)
                    blob.content_type = 'video/mp4'
                    
                    with open(output_path, 'rb') as video_file:
                        blob.upload_from_file(video_file)
                    
                    app.logger.info(f'[INFO] Upload para {blob_name} concluído')
                    
                    # Gerar signed URL válida por 24 horas
                    from datetime import datetime, timedelta
                    signed_url = blob.generate_signed_url(
                        expiration=datetime.utcnow() + timedelta(hours=24),
                        method='GET'
                    )
                    progress_data[key]['signed_url'] = signed_url
                    progress_data[key]['public_url'] = f'gs://{bucket_name}/{blob_name}'
                    
                    progress_callback('Upload concluído! Vídeo pronto para download.', 100)
                    
                except Exception as upload_error:
                    app.logger.error(f'[ERROR] Falha no upload: {str(upload_error)}')
                    progress_data[key]['message'] = f'Vídeo criado mas falha no upload: {str(upload_error)}'
                    # Ainda assim, deixa o arquivo local disponível
                    progress_data[key]['local_file'] = output_path

                app.logger.info('[INFO] Processo finalizado com sucesso')
            except Exception as e:
                error_msg = f'[ERROR] Falha na montagem do vídeo: {traceback.format_exc()}'
                progress_data[key]['message'] = error_msg
                app.logger.error(error_msg)
            finally:
                # Limpeza de arquivos temporários
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                app.logger.info(f'[INFO] Arquivos temporários em {temp_dir} removidos')
        
        thread = threading.Thread(target=create_video_thread)
        thread.start()
        
        return jsonify({'success': True, 'session_id': session_id, 'message': 'Criação do vídeo iniciada.'})
        
    except Exception as e:
        app.logger.error(f'[ERROR] Erro em /create_video: {traceback.format_exc()}')
        return jsonify({'error': str(e)}), 500

@app.route('/transcribe_tiktok', methods=['POST'])
def transcribe_tiktok():
    app.logger.info('[INFO] POST /transcribe_tiktok iniciado')
    try:
        url = request.form.get('url')
        if not url: return jsonify({'error': 'Nenhum link do TikTok fornecido.'}), 400
        
        cookies_path = None
        if os.path.exists('/app/cookies.txt'):
            cookies_path = '/app/cookies.txt'
            app.logger.info(f'[INFO] Usando cookies existentes em {cookies_path}')
        
        app.logger.info(f'[INFO] URL do TikTok recebida: {url}')
        if cookies_path:
            app.logger.info('[INFO] Usando arquivo de cookies do sistema')
        else:
            app.logger.info('[INFO] Nenhum arquivo de cookies disponível')
        
        session_id = os.path.basename(tempfile.mkdtemp())
        key = f"{session_id}_transcribe"
        progress_data[key] = {'progress': 0, 'message': 'Iniciando transcrição...'}
        
        def progress_callback(message, progress=None):
            if progress is not None: progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
            app.logger.info(f'[INFO] Progresso: {message} ({progress}%)' if progress else f'[INFO] {message}')
        
        def transcribe_thread():
            try:
                app.logger.info('[INFO] Iniciando processamento de transcrição')
                result = transcribe_tiktok_video(url, progress_callback, cookies_path)
                transcription_results[session_id] = result
                if result['success']:
                    progress_data[key]['progress'] = 100
                    progress_data[key]['message'] = 'Transcrição completa!'
                    app.logger.info('[INFO] Transcrição completada com sucesso')
                else:
                    error_msg = f"[ERROR] Falha na transcrição: {result.get('error', 'Erro desconhecido')}"
                    progress_data[key]['message'] = error_msg
                    app.logger.error(error_msg)
            except Exception as e:
                error_message = f'[ERROR] Erro na thread: {traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                app.logger.error(error_message)
            finally:
                app.logger.info('[INFO] Processo de transcrição finalizado')
        
        thread = threading.Thread(target=transcribe_thread)
        thread.start()
        
        return jsonify({'success': True, 'session_id': session_id, 'message': 'Transcrição iniciada.'})
        
    except Exception as e:
        app.logger.error(f'[ERROR] Erro em /transcribe_tiktok: {traceback.format_exc()}')
        return jsonify({'error': str(e)}), 500

@app.route('/upload_video', methods=['POST'])
def upload_video():
    try:
        temp_dir = tempfile.mkdtemp()
        video_file = request.files.get('video')
        if not video_file or video_file.filename == '':
            return jsonify({'error': 'Nenhum arquivo de vídeo enviado'}), 400
        
        video_filename = secure_filename(f"input_{video_file.filename}")
        video_path = os.path.join(temp_dir, video_filename)
        video_file.save(video_path)
        
        return jsonify({
            'success': True,
            'session_id': os.path.basename(temp_dir),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/progress')
def get_progress():
    session_id = request.args.get('session_id')
    task_type = request.args.get('type')
    if not session_id or not task_type:
        return jsonify({'error': 'session_id e type são necessários'}), 400
    key = f"{session_id}_{task_type}"
    progress = progress_data.get(key, {'progress': 0, 'message': 'Aguardando...'})
    if 'signed_url' in progress_data.get(key, {}):
        progress['signed_url'] = progress_data[key]['signed_url']
    return jsonify(progress)

@app.route('/download/<session_id>')
def download_video(session_id):
    try:
        temp_dir = os.path.join(tempfile.gettempdir(), session_id)
        # Tenta encontrar um arquivo .mp4 no diretório
        output_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
        if not output_files:
            return "Arquivo de vídeo não encontrado.", 404
        
        output_path = os.path.join(temp_dir, output_files[0])
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

# Endpoints de multi download removidos conforme solicitado