import os
import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
from google.cloud import storage
from google.cloud.exceptions import NotFound
import uuid
import time

class StorageManager:
    """Manages Google Cloud Storage operations for video processing"""
    
    def __init__(self, bucket_name: str = None):
        self.logger = logging.getLogger(__name__)
        self.client = storage.Client()
        
        # Use environment variable or default bucket name
        self.bucket_name = bucket_name or os.getenv('GCS_BUCKET_NAME', 'dark-creator-video-storage')
        
        try:
            self.bucket = self.client.bucket(self.bucket_name)
            # Test bucket access
            self.bucket.exists()
            self.logger.info(f"Connected to bucket: {self.bucket_name}")
        except Exception as e:
            self.logger.error(f"Failed to connect to bucket {self.bucket_name}: {str(e)}")
            raise
    
    def upload_file(self, local_path: str, blob_name: str = None, 
                   content_type: str = None, progress_callback=None) -> str:
        """Upload a file to Google Cloud Storage
        
        Args:
            local_path: Path to local file
            blob_name: Name for the blob in storage (if None, uses filename)
            content_type: MIME type of the file
            progress_callback: Function to call with upload progress
            
        Returns:
            Public URL of the uploaded file
        """
        try:
            if not os.path.exists(local_path):
                raise FileNotFoundError(f"Local file not found: {local_path}")
            
            # Generate blob name if not provided
            if blob_name is None:
                filename = os.path.basename(local_path)
                timestamp = int(time.time())
                blob_name = f"uploads/{timestamp}_{filename}"
            
            blob = self.bucket.blob(blob_name)
            
            # Set content type if provided
            if content_type:
                blob.content_type = content_type
            
            # Upload with progress tracking
            file_size = os.path.getsize(local_path)
            
            def upload_progress(bytes_transferred):
                if progress_callback and file_size > 0:
                    progress = (bytes_transferred / file_size) * 100
                    progress_callback(f"Uploading... {progress:.1f}%", progress)
            
            if progress_callback:
                progress_callback("Starting upload...", 0)
            
            # Upload the file
            with open(local_path, 'rb') as file_obj:
                blob.upload_from_file(file_obj, content_type=content_type)
            
            if progress_callback:
                progress_callback("Upload completed!", 100)
            
            # Make the blob publicly readable
            blob.make_public()
            
            public_url = blob.public_url
            self.logger.info(f"File uploaded successfully: {public_url}")
            
            return public_url
            
        except Exception as e:
            self.logger.error(f"Error uploading file {local_path}: {str(e)}")
            if progress_callback:
                progress_callback(f"Upload failed: {str(e)}", 0)
            raise
    
    def download_file(self, blob_name: str, local_path: str = None, 
                     progress_callback=None) -> str:
        """Download a file from Google Cloud Storage
        
        Args:
            blob_name: Name of the blob in storage
            local_path: Local path to save the file (if None, uses temp file)
            progress_callback: Function to call with download progress
            
        Returns:
            Path to the downloaded file
        """
        try:
            blob = self.bucket.blob(blob_name)
            
            if not blob.exists():
                raise NotFound(f"Blob not found: {blob_name}")
            
            # Generate local path if not provided
            if local_path is None:
                temp_dir = tempfile.gettempdir()
                filename = os.path.basename(blob_name)
                local_path = os.path.join(temp_dir, filename)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            if progress_callback:
                progress_callback("Starting download...", 0)
            
            # Download the file
            blob.download_to_filename(local_path)
            
            if progress_callback:
                progress_callback("Download completed!", 100)
            
            self.logger.info(f"File downloaded successfully: {local_path}")
            return local_path
            
        except Exception as e:
            self.logger.error(f"Error downloading file {blob_name}: {str(e)}")
            if progress_callback:
                progress_callback(f"Download failed: {str(e)}", 0)
            raise
    
    def delete_file(self, blob_name: str) -> bool:
        """Delete a file from Google Cloud Storage
        
        Args:
            blob_name: Name of the blob to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            blob = self.bucket.blob(blob_name)
            blob.delete()
            self.logger.info(f"File deleted successfully: {blob_name}")
            return True
            
        except NotFound:
            self.logger.warning(f"File not found for deletion: {blob_name}")
            return False
        except Exception as e:
            self.logger.error(f"Error deleting file {blob_name}: {str(e)}")
            return False
    
    def list_files(self, prefix: str = None, max_results: int = 100) -> List[Dict[str, Any]]:
        """List files in the bucket
        
        Args:
            prefix: Filter files by prefix
            max_results: Maximum number of results to return
            
        Returns:
            List of file information dictionaries
        """
        try:
            blobs = self.bucket.list_blobs(prefix=prefix, max_results=max_results)
            
            files = []
            for blob in blobs:
                files.append({
                    'name': blob.name,
                    'size': blob.size,
                    'created': blob.time_created,
                    'updated': blob.updated,
                    'content_type': blob.content_type,
                    'public_url': blob.public_url if blob.public_url_set else None
                })
            
            return files
            
        except Exception as e:
            self.logger.error(f"Error listing files: {str(e)}")
            return []
    
    def get_signed_url(self, blob_name: str, expiration_minutes: int = 60) -> str:
        """Generate a signed URL for temporary access to a file
        
        Args:
            blob_name: Name of the blob
            expiration_minutes: URL expiration time in minutes
            
        Returns:
            Signed URL for the file
        """
        try:
            blob = self.bucket.blob(blob_name)
            
            from datetime import datetime, timedelta
            expiration = datetime.utcnow() + timedelta(minutes=expiration_minutes)
            
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=expiration,
                method="GET"
            )
            
            return signed_url
            
        except Exception as e:
            self.logger.error(f"Error generating signed URL for {blob_name}: {str(e)}")
            raise
    
    def cleanup_old_files(self, prefix: str = None, days_old: int = 7) -> int:
        """Clean up files older than specified days
        
        Args:
            prefix: Filter files by prefix
            days_old: Delete files older than this many days
            
        Returns:
            Number of files deleted
        """
        try:
            from datetime import datetime, timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            blobs = self.bucket.list_blobs(prefix=prefix)
            deleted_count = 0
            
            for blob in blobs:
                if blob.time_created < cutoff_date:
                    try:
                        blob.delete()
                        deleted_count += 1
                        self.logger.info(f"Deleted old file: {blob.name}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete {blob.name}: {str(e)}")
            
            self.logger.info(f"Cleanup completed. Deleted {deleted_count} files.")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")
            return 0
    
    def create_session_folder(self, session_id: str) -> str:
        """Create a session-specific folder prefix
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            Folder prefix for the session
        """
        timestamp = int(time.time())
        return f"sessions/{timestamp}_{session_id}"
    
    def upload_multiple_files(self, file_paths: List[str], session_id: str = None, 
                            progress_callback=None) -> List[Dict[str, str]]:
        """Upload multiple files to storage
        
        Args:
            file_paths: List of local file paths
            session_id: Session ID for organizing files
            progress_callback: Function to call with overall progress
            
        Returns:
            List of dictionaries with local_path, blob_name, and public_url
        """
        try:
            if not file_paths:
                return []
            
            # Create session folder if provided
            folder_prefix = self.create_session_folder(session_id) if session_id else "uploads"
            
            results = []
            total_files = len(file_paths)
            
            for i, file_path in enumerate(file_paths):
                if progress_callback:
                    overall_progress = (i / total_files) * 100
                    progress_callback(f"Uploading file {i+1}/{total_files}...", overall_progress)
                
                try:
                    filename = os.path.basename(file_path)
                    blob_name = f"{folder_prefix}/{filename}"
                    
                    public_url = self.upload_file(file_path, blob_name)
                    
                    results.append({
                        'local_path': file_path,
                        'blob_name': blob_name,
                        'public_url': public_url,
                        'filename': filename
                    })
                    
                except Exception as e:
                    self.logger.error(f"Failed to upload {file_path}: {str(e)}")
                    results.append({
                        'local_path': file_path,
                        'blob_name': None,
                        'public_url': None,
                        'filename': os.path.basename(file_path),
                        'error': str(e)
                    })
            
            if progress_callback:
                progress_callback("All uploads completed!", 100)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error in multiple file upload: {str(e)}")
            if progress_callback:
                progress_callback(f"Upload failed: {str(e)}", 0)
            raise