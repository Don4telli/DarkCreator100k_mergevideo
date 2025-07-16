# ==============================================================================
# BLOCO DE CORREÇÃO PARA AMBIENTES DE SERVIDOR (RENDER/VERCEL)
# ==============================================================================
from pathlib import Path
import sys
# Adiciona o diretório raiz do projeto (a pasta pai da pasta 'api') ao path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
# ==============================================================================

import os
import threading
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import tempfile
import shutil

from core.video_processor import VideoProcessor
from core.tiktok_transcription import transcribe_tiktok_video

# ==============================================================================
# CORREÇÃO FINAL - DIZENDO AO FLASK ONDE FICA A PASTA 'templates'
# ==============================================================================
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
app = Flask(__name__, template_folder=TEMPLATE_DIR)
# ==============================================================================

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# Variáveis globais para rastrear o progresso
progress_data = {}
transcription_results = {}
video_processor = VideoProcessor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        temp_dir = tempfile.mkdtemp()
        image_files = request.files.getlist('images')
        if not image_files or len(image_files) == 0:
            return jsonify({'error': 'No image files provided'}), 400
        
        image_paths = []
        for i, file in enumerate(image_files):
            if file.filename == '': continue
            filename = secure_filename(f"image_{i:03d}_{file.filename}")
            filepath = os.path.join(temp_dir, filename)
            file.save(filepath)
            image_paths.append(filepath)
        
        if not image_paths: return jsonify({'error': 'No valid image files uploaded'}), 400
        
        audio_path = None
        if 'audio' in request.files and request.files['audio'].filename != '':
            audio_file = request.files['audio']
            audio_filename = secure_filename(f"audio_{audio_file.filename}")
            audio_path = os.path.join(temp_dir, audio_filename)
            audio_file.save(audio_path)
        
        # Guardar no dicionário para a próxima etapa (simulando sessão)
        session_id = os.path.basename(temp_dir)
        progress_data[session_id] = {'image_paths': image_paths, 'audio_path': audio_path}
        
        return jsonify({
            'success': True,
            'session_id': session_id,
        })
        
    except Exception as e:
        app.logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/create_video', methods=['POST'])
def create_video():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id or session_id not in progress_data:
            return jsonify({'error': 'Session expired or invalid'}), 400
        
        session_info = progress_data[session_id]
        image_paths = session_info['image_paths']
        audio_path = session_info['audio_path']
        
        temp_dir = os.path.dirname(image_paths[0])
        output_path = os.path.join(temp_dir, 'output.mp4')
        
        aspect_ratio = data.get('aspect_ratio', '9:16')
        fps = data.get('fps', 30)
        multi_video_mode = data.get('multi_video_mode', True)
        green_screen_duration = data.get('green_screen_duration', 5.0)
        
        key = f"{session_id}_create"
        progress_data[key] = {'progress': 0, 'message': 'Starting video creation...'}
        
        def progress_callback(message, progress=None):
            if progress is not None: progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
        
        def create_video_thread():
            try:
                if multi_video_mode:
                    video_processor.create_multi_video_with_separators(
                        image_paths=image_paths, audio_path=audio_path, output_path=output_path,
                        aspect_ratio=aspect_ratio, fps=fps, green_screen_duration=green_screen_duration,
                        progress_callback=progress_callback
                    )
                else:
                    # Este bloco pode precisar de ajustes dependendo do que o cliente envia
                    width, height = video_processor.get_aspect_ratio_dimensions(aspect_ratio)
                    video_processor.create_video_from_images(
                        image_paths=image_paths, audio_path=audio_path, output_path=output_path,
                        width=width, height=height, fps=fps, progress_callback=progress_callback
                    )
                progress_data[key]['progress'] = 100
                progress_data[key]['message'] = 'Video creation completed!'
            except Exception as e:
                import traceback
                error_message = f'Error: {e}\nTraceback:\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                app.logger.error(error_message)
        
        thread = threading.Thread(target=create_video_thread)
        thread.start()
        
        return jsonify({'success': True, 'message': 'Video creation started'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/transcribe_tiktok', methods=['POST'])
def transcribe_tiktok():
    try:
        data = request.get_json()
        url = data.get('url')
        if not url: return jsonify({'error': 'No TikTok URL provided'}), 400
        
        session_id = os.path.basename(tempfile.mkdtemp())
        key = f"{session_id}_transcribe"
        progress_data[key] = {'progress': 0, 'message': 'Starting TikTok transcription...'}
        
        def progress_callback(message, progress=None):
            if progress is not None: progress_data[key]['progress'] = progress
            progress_data[key]['message'] = message
        
        def transcribe_thread(): # Nome da função corrigido
            try:
                result = transcribe_tiktok_video(url, progress_callback)
                transcription_results[session_id] = result
                if result['success']:
                    progress_data[key]['progress'] = 100
                    progress_data[key]['message'] = 'Transcription completed successfully!'
                else:
                    progress_data[key]['message'] = f'Transcription failed: {result.get("error", "Unknown error")}'
            except Exception as e:
                import traceback
                error_message = f'Error: {e}\nTraceback\n{traceback.format_exc()}'
                progress_data[key]['message'] = error_message
                transcription_results[session_id] = {'success': False, 'error': error_message}
                app.logger.error(error_message)
        
        # **A CORREÇÃO ESTÁ AQUI**
        thread = threading.Thread(target=transcribe_thread) # Alvo da thread corrigido
        thread.start()
        
        return jsonify({'success': True, 'session_id': session_id, 'message': 'Transcription started'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Suas outras rotas (/progress, /download, etc.) continuam iguais
@app.route('/progress')
def get_progress():
    session_id = request.args.get('session_id')
    task_type = request.args.get('type', 'create')
    if not session_id:
        return jsonify({'error': 'Session ID required'}), 400
    key = f"{session_id}_{task_type}"
    return jsonify(progress_data.get(key, {'progress': 0, 'message': 'Waiting...'}))

@app.route('/download/<session_id>')
def download_video(session_id):
    try:
        temp_dir = os.path.join(tempfile.gettempdir(), session_id)
        output_path = os.path.join(temp_dir, 'output.mp4')
        if not os.path.exists(output_path):
            return jsonify({'error': 'Video file not found'}), 404
        return send_file(output_path, as_attachment=True, download_name='video_output.mp4')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_transcription/<session_id>')
def get_transcription(session_id):
    try:
        if session_id not in transcription_results:
            return jsonify({'error': 'Transcription not found or still in progress'}), 404
        result = transcription_results[session_id]
        if result['success']:
            return jsonify({
                'success': True, 'text': result['text'], 'session_id': session_id,
                'url': result.get('url', '')
            })
        else:
            return jsonify({
                'success': False, 'error': result.get('error', 'Unknown error'),
                'session_id': session_id
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500