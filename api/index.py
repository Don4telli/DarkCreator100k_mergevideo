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
from core.multi_video_downloader import MultiVideoDownloader
from core.storage_manager import StorageManager

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

# Inicializar gerenciadores de storage e download múltiplo
storage_manager = StorageManager()
multi_downloader = MultiVideoDownloader(storage_manager)

@app.route('/')
def index():
    print("Passei aqui na /")
    logging.info("Passei aqui também na /")
    return render_template('index.html')

@app.route('/multi_download')
def multi_download_page():
    """Serve the multi-download page"""
    return render_template('multi_download.html')

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
                bucket = storage_client.bucket(bucket_name)
                blob_name = f'videos/{session_id}/{output_filename}'
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(output_path)
                app.logger.info(f'[INFO] Upload para gs://{bucket_name}/{blob_name} concluído')

                # Gerar signed URL válida por 1 hora
                signed_url = blob.generate_signed_url(expiration=3600, method='GET')
                progress_data[key]['signed_url'] = signed_url

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

@app.route('/download_multiple_tiktoks', methods=['POST'])
def download_multiple_tiktoks():
    """Download multiple TikTok videos and store in Google Cloud Storage"""
    app.logger.info('[INFO] POST /download_multiple_tiktoks iniciado')
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados JSON são necessários'}), 400
        
        urls = data.get('urls', [])
        if not urls or not isinstance(urls, list):
            return jsonify({'error': 'Lista de URLs do TikTok é necessária'}), 400
        
        if len(urls) > 20:  # Limit to prevent abuse
            return jsonify({'error': 'Máximo de 20 URLs por vez'}), 400
        
        max_workers = min(data.get('max_workers', 3), 5)  # Limit concurrent downloads
        session_id = data.get('session_id')  # Optional custom session ID
        
        # Check for cookies
        cookies_path = None
        if os.path.exists('/app/cookies.txt'):
            cookies_path = '/app/cookies.txt'
            app.logger.info('[INFO] Usando cookies do sistema para autenticação')
        
        app.logger.info(f'[INFO] Iniciando download de {len(urls)} vídeos do TikTok')
        
        # Generate session ID if not provided
        if not session_id:
            session_id = os.path.basename(tempfile.mkdtemp())
        
        key = f"{session_id}_multi_download"
        progress_data[key] = {
            'progress': 0, 
            'message': f'Iniciando download de {len(urls)} vídeos...',
            'session_id': session_id,
            'total_videos': len(urls),
            'completed': 0,
            'failed': 0
        }
        
        def progress_callback(message, progress=None):
            if progress is not None:
                progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
            app.logger.info(f'[INFO] Multi-download progress: {message} ({progress}%)' if progress else f'[INFO] {message}')
        
        def download_thread():
            try:
                app.logger.info('[INFO] Iniciando processamento de múltiplos downloads')
                
                result = multi_downloader.download_multiple_videos(
                    urls=urls,
                    session_id=session_id,
                    max_workers=max_workers,
                    progress_callback=progress_callback,
                    cookies_path=cookies_path
                )
                
                # Store results
                progress_data[key]['download_result'] = result
                progress_data[key]['progress'] = 100
                progress_data[key]['message'] = f'Download completo! {result["successful_downloads"]}/{result["total_videos"]} vídeos baixados com sucesso'
                progress_data[key]['completed'] = result['successful_downloads']
                progress_data[key]['failed'] = result['failed_downloads']
                
                app.logger.info(f'[INFO] Multi-download completado: {result["successful_downloads"]}/{result["total_videos"]} sucessos')
                
            except Exception as e:
                error_message = f'[ERROR] Erro no multi-download: {traceback.format_exc()}'
                progress_data[key]['message'] = f'Erro no download: {str(e)}'
                progress_data[key]['error'] = str(e)
                app.logger.error(error_message)
            finally:
                app.logger.info('[INFO] Processo de multi-download finalizado')
        
        thread = threading.Thread(target=download_thread)
        thread.start()
        
        return jsonify({
            'success': True, 
            'session_id': session_id, 
            'message': f'Download de {len(urls)} vídeos iniciado.',
            'total_videos': len(urls)
        })
        
    except Exception as e:
        app.logger.error(f'[ERROR] Erro em /download_multiple_tiktoks: {traceback.format_exc()}')
        return jsonify({'error': str(e)}), 500

@app.route('/multi_download_progress/<session_id>')
def get_multi_download_progress(session_id):
    """Get progress for multi-video download"""
    try:
        key = f"{session_id}_multi_download"
        progress = progress_data.get(key, {
            'progress': 0, 
            'message': 'Sessão não encontrada',
            'error': 'Session not found'
        })
        
        # Add summary from multi_downloader if available
        if 'download_result' not in progress:
            summary = multi_downloader.get_download_summary(session_id)
            if 'error' not in summary:
                progress.update(summary)
        
        return jsonify(progress)
        
    except Exception as e:
        app.logger.error(f'[ERROR] Erro ao obter progresso: {str(e)}')
        return jsonify({
            'progress': 0,
            'message': f'Erro ao obter progresso: {str(e)}',
            'error': str(e)
        }), 500

@app.route('/multi_download_result/<session_id>')
def get_multi_download_result(session_id):
    """Get detailed results for multi-video download"""
    try:
        key = f"{session_id}_multi_download"
        progress = progress_data.get(key, {})
        
        if 'download_result' not in progress:
            return jsonify({'error': 'Download ainda em progresso ou sessão não encontrada'}), 404
        
        result = progress['download_result']
        
        # Add signed URLs for storage files
        if 'storage_results' in result and 'uploaded_files' in result['storage_results']:
            for file_info in result['storage_results']['uploaded_files']:
                try:
                    # Generate signed URL valid for 24 hours
                    signed_url = storage_manager.generate_signed_url(
                        file_info['blob_name'], 
                        expiration_hours=24
                    )
                    file_info['signed_url'] = signed_url
                except Exception as e:
                    app.logger.warning(f'Failed to generate signed URL for {file_info["blob_name"]}: {str(e)}')
        
        return jsonify(result)
        
    except Exception as e:
        app.logger.error(f'[ERROR] Erro ao obter resultado: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup_session/<session_id>', methods=['DELETE'])
def cleanup_session(session_id):
    """Clean up session data and optionally storage files"""
    try:
        keep_storage = request.args.get('keep_storage', 'true').lower() == 'true'
        
        # Clean up multi-downloader session
        cleanup_success = multi_downloader.cleanup_session(session_id, keep_storage)
        
        # Clean up progress data
        keys_to_remove = [key for key in progress_data.keys() if session_id in key]
        for key in keys_to_remove:
            del progress_data[key]
        
        # Clean up transcription results
        if session_id in transcription_results:
            del transcription_results[session_id]
        
        app.logger.info(f'[INFO] Session {session_id} cleaned up (keep_storage={keep_storage})')
        
        return jsonify({
            'success': cleanup_success,
            'message': f'Session {session_id} cleaned up successfully',
            'kept_storage': keep_storage
        })
        
    except Exception as e:
        app.logger.error(f'[ERROR] Erro na limpeza da sessão: {str(e)}')
        return jsonify({'error': str(e)}), 500