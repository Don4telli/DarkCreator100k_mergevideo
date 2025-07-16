import os
import logging
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import uuid

from .tiktok_transcription import TikTokTranscriber
from .storage_manager import StorageManager

class MultiVideoDownloader:
    """Downloads multiple TikTok videos and manages them using Google Cloud Storage"""
    
    def __init__(self, storage_manager: StorageManager = None):
        self.logger = logging.getLogger(__name__)
        self.storage_manager = storage_manager or StorageManager()
        self.transcriber = TikTokTranscriber()
        
        # Thread-safe progress tracking
        self._progress_lock = threading.Lock()
        self._progress_data = {}
    
    def download_multiple_videos(self, urls: List[str], session_id: str = None, 
                               max_workers: int = 3, progress_callback: Callable = None,
                               cookies_path: str = None) -> Dict[str, Any]:
        """Download multiple TikTok videos and upload to storage
        
        Args:
            urls: List of TikTok URLs to download
            session_id: Unique session identifier
            max_workers: Maximum number of concurrent downloads
            progress_callback: Function to call with progress updates
            cookies_path: Path to cookies file for authentication
            
        Returns:
            Dictionary with download results and storage information
        """
        try:
            if not urls:
                raise ValueError("No URLs provided")
            
            # Generate session ID if not provided
            if session_id is None:
                session_id = str(uuid.uuid4())
            
            # Initialize progress tracking
            with self._progress_lock:
                self._progress_data[session_id] = {
                    'total_videos': len(urls),
                    'completed': 0,
                    'failed': 0,
                    'current_status': 'Starting downloads...',
                    'results': [],
                    'storage_info': {
                        'session_folder': self.storage_manager.create_session_folder(session_id),
                        'uploaded_files': []
                    }
                }
            
            if progress_callback:
                progress_callback(f"Starting download of {len(urls)} videos...", 0)
            
            # Create temporary directory for downloads
            temp_dir = tempfile.mkdtemp(prefix=f"tiktok_downloads_{session_id}_")
            
            try:
                # Download videos concurrently
                results = self._download_videos_concurrent(
                    urls, temp_dir, session_id, max_workers, 
                    progress_callback, cookies_path
                )
                
                # Upload successful downloads to storage
                if progress_callback:
                    progress_callback("Uploading videos to storage...", 80)
                
                storage_results = self._upload_to_storage(
                    results, session_id, progress_callback
                )
                
                # Prepare final response
                final_result = {
                    'session_id': session_id,
                    'total_videos': len(urls),
                    'successful_downloads': len([r for r in results if r['success']]),
                    'failed_downloads': len([r for r in results if not r['success']]),
                    'download_results': results,
                    'storage_results': storage_results,
                    'storage_info': self._progress_data[session_id]['storage_info']
                }
                
                if progress_callback:
                    progress_callback("All downloads completed!", 100)
                
                return final_result
                
            finally:
                # Clean up temporary directory
                try:
                    shutil.rmtree(temp_dir)
                    self.logger.info(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up temp directory {temp_dir}: {str(e)}")
            
        except Exception as e:
            self.logger.error(f"Error in multi-video download: {str(e)}")
            if progress_callback:
                progress_callback(f"Download failed: {str(e)}", 0)
            raise
    
    def _download_videos_concurrent(self, urls: List[str], temp_dir: str, 
                                  session_id: str, max_workers: int,
                                  progress_callback: Callable, 
                                  cookies_path: str) -> List[Dict[str, Any]]:
        """Download videos using concurrent threads"""
        results = []
        
        def download_single_video(url_index_tuple):
            url, index = url_index_tuple
            try:
                self.logger.info(f"Starting download {index+1}/{len(urls)}: {url}")
                
                # Update progress
                self._update_progress(session_id, f"Downloading video {index+1}/{len(urls)}...")
                
                # Create unique filename for this video
                video_filename = f"video_{index+1:03d}_{int(time.time())}.mp4"
                audio_filename = f"audio_{index+1:03d}_{int(time.time())}.mp3"
                
                video_path = os.path.join(temp_dir, video_filename)
                audio_path = os.path.join(temp_dir, audio_filename)
                
                # Download video and extract audio
                download_result = self.transcriber.download_tiktok_video(
                    url, video_path, audio_path, cookies_path
                )
                
                if download_result['success']:
                    # Transcribe audio if available
                    transcription = None
                    if os.path.exists(audio_path):
                        try:
                            transcription_result = self.transcriber.transcribe_audio(audio_path)
                            if transcription_result['success']:
                                transcription = transcription_result['transcription']
                        except Exception as e:
                            self.logger.warning(f"Transcription failed for {url}: {str(e)}")
                    
                    result = {
                        'url': url,
                        'index': index,
                        'success': True,
                        'video_path': video_path if os.path.exists(video_path) else None,
                        'audio_path': audio_path if os.path.exists(audio_path) else None,
                        'transcription': transcription,
                        'message': 'Download successful'
                    }
                    
                    # Update progress
                    self._update_progress(session_id, completed=True)
                    
                else:
                    result = {
                        'url': url,
                        'index': index,
                        'success': False,
                        'video_path': None,
                        'audio_path': None,
                        'transcription': None,
                        'error': download_result.get('error', 'Unknown error'),
                        'message': f"Download failed: {download_result.get('error', 'Unknown error')}"
                    }
                    
                    # Update progress
                    self._update_progress(session_id, failed=True)
                
                return result
                
            except Exception as e:
                self.logger.error(f"Error downloading {url}: {str(e)}")
                self._update_progress(session_id, failed=True)
                return {
                    'url': url,
                    'index': index,
                    'success': False,
                    'video_path': None,
                    'audio_path': None,
                    'transcription': None,
                    'error': str(e),
                    'message': f"Download failed: {str(e)}"
                }
        
        # Execute downloads concurrently
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all download tasks
            future_to_url = {
                executor.submit(download_single_video, (url, i)): (url, i) 
                for i, url in enumerate(urls)
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_url):
                url, index = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    # Update overall progress
                    if progress_callback:
                        completed = len([r for r in results if r['success']])
                        failed = len([r for r in results if not r['success']])
                        total_processed = completed + failed
                        progress = min(70, (total_processed / len(urls)) * 70)  # Up to 70% for downloads
                        
                        progress_callback(
                            f"Downloaded {total_processed}/{len(urls)} videos (Success: {completed}, Failed: {failed})",
                            progress
                        )
                        
                except Exception as e:
                    self.logger.error(f"Error processing result for {url}: {str(e)}")
                    results.append({
                        'url': url,
                        'index': index,
                        'success': False,
                        'video_path': None,
                        'audio_path': None,
                        'transcription': None,
                        'error': str(e),
                        'message': f"Processing failed: {str(e)}"
                    })
        
        # Sort results by index to maintain order
        results.sort(key=lambda x: x['index'])
        return results
    
    def _upload_to_storage(self, download_results: List[Dict[str, Any]], 
                          session_id: str, progress_callback: Callable) -> Dict[str, Any]:
        """Upload downloaded files to Google Cloud Storage"""
        try:
            successful_downloads = [r for r in download_results if r['success']]
            
            if not successful_downloads:
                return {
                    'uploaded_files': [],
                    'total_uploaded': 0,
                    'upload_errors': [],
                    'message': 'No files to upload'
                }
            
            # Collect all files to upload
            files_to_upload = []
            for result in successful_downloads:
                if result['video_path'] and os.path.exists(result['video_path']):
                    files_to_upload.append({
                        'path': result['video_path'],
                        'type': 'video',
                        'url': result['url'],
                        'index': result['index']
                    })
                if result['audio_path'] and os.path.exists(result['audio_path']):
                    files_to_upload.append({
                        'path': result['audio_path'],
                        'type': 'audio',
                        'url': result['url'],
                        'index': result['index']
                    })
            
            if not files_to_upload:
                return {
                    'uploaded_files': [],
                    'total_uploaded': 0,
                    'upload_errors': [],
                    'message': 'No valid files found to upload'
                }
            
            # Upload files to storage
            uploaded_files = []
            upload_errors = []
            
            for i, file_info in enumerate(files_to_upload):
                try:
                    if progress_callback:
                        upload_progress = 80 + (i / len(files_to_upload)) * 15  # 80-95% for uploads
                        progress_callback(
                            f"Uploading {file_info['type']} file {i+1}/{len(files_to_upload)}...",
                            upload_progress
                        )
                    
                    # Generate blob name
                    filename = os.path.basename(file_info['path'])
                    blob_name = f"{self._progress_data[session_id]['storage_info']['session_folder']}/{filename}"
                    
                    # Determine content type
                    content_type = 'video/mp4' if file_info['type'] == 'video' else 'audio/mpeg'
                    
                    # Upload file
                    public_url = self.storage_manager.upload_file(
                        file_info['path'], blob_name, content_type
                    )
                    
                    upload_info = {
                        'local_path': file_info['path'],
                        'blob_name': blob_name,
                        'public_url': public_url,
                        'file_type': file_info['type'],
                        'original_url': file_info['url'],
                        'video_index': file_info['index'],
                        'filename': filename
                    }
                    
                    uploaded_files.append(upload_info)
                    
                    # Update storage info in progress data
                    with self._progress_lock:
                        self._progress_data[session_id]['storage_info']['uploaded_files'].append(upload_info)
                    
                except Exception as e:
                    error_info = {
                        'file_path': file_info['path'],
                        'file_type': file_info['type'],
                        'error': str(e)
                    }
                    upload_errors.append(error_info)
                    self.logger.error(f"Failed to upload {file_info['path']}: {str(e)}")
            
            return {
                'uploaded_files': uploaded_files,
                'total_uploaded': len(uploaded_files),
                'upload_errors': upload_errors,
                'message': f"Uploaded {len(uploaded_files)} files successfully"
            }
            
        except Exception as e:
            self.logger.error(f"Error uploading files to storage: {str(e)}")
            return {
                'uploaded_files': [],
                'total_uploaded': 0,
                'upload_errors': [{'error': str(e)}],
                'message': f"Upload failed: {str(e)}"
            }
    
    def _update_progress(self, session_id: str, status: str = None, 
                        completed: bool = False, failed: bool = False):
        """Thread-safe progress update"""
        with self._progress_lock:
            if session_id in self._progress_data:
                if status:
                    self._progress_data[session_id]['current_status'] = status
                if completed:
                    self._progress_data[session_id]['completed'] += 1
                if failed:
                    self._progress_data[session_id]['failed'] += 1
    
    def get_progress(self, session_id: str) -> Dict[str, Any]:
        """Get current progress for a session"""
        with self._progress_lock:
            return self._progress_data.get(session_id, {})
    
    def cleanup_session(self, session_id: str, keep_storage: bool = True) -> bool:
        """Clean up session data
        
        Args:
            session_id: Session to clean up
            keep_storage: Whether to keep files in storage (default: True)
            
        Returns:
            True if cleanup was successful
        """
        try:
            # Remove from progress tracking
            with self._progress_lock:
                if session_id in self._progress_data:
                    storage_info = self._progress_data[session_id].get('storage_info', {})
                    del self._progress_data[session_id]
                else:
                    storage_info = {}
            
            # Optionally clean up storage files
            if not keep_storage and storage_info.get('uploaded_files'):
                for file_info in storage_info['uploaded_files']:
                    try:
                        self.storage_manager.delete_file(file_info['blob_name'])
                    except Exception as e:
                        self.logger.warning(f"Failed to delete {file_info['blob_name']}: {str(e)}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error cleaning up session {session_id}: {str(e)}")
            return False
    
    def get_download_summary(self, session_id: str) -> Dict[str, Any]:
        """Get a summary of downloads for a session"""
        progress_data = self.get_progress(session_id)
        
        if not progress_data:
            return {'error': 'Session not found'}
        
        return {
            'session_id': session_id,
            'total_videos': progress_data.get('total_videos', 0),
            'completed': progress_data.get('completed', 0),
            'failed': progress_data.get('failed', 0),
            'current_status': progress_data.get('current_status', 'Unknown'),
            'storage_info': progress_data.get('storage_info', {}),
            'is_complete': (progress_data.get('completed', 0) + progress_data.get('failed', 0)) >= progress_data.get('total_videos', 0)
        }