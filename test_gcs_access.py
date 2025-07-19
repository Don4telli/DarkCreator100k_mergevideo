#!/usr/bin/env python3
"""
Teste de acesso ao Google Cloud Storage
Este script testa se conseguimos conectar e fazer operações básicas no GCS.
"""

from google.cloud import storage
import tempfile
import os
from datetime import datetime, timedelta

BUCKET_NAME = "darkcreator100k-mergevideo"

def test_gcs_connection():
    """Testa a conexão básica com o GCS"""
    try:
        print("🔍 Testando conexão com Google Cloud Storage...")
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        
        # Verificar se o bucket existe
        if bucket.exists():
            print(f"✅ Bucket '{BUCKET_NAME}' encontrado!")
            return True
        else:
            print(f"❌ Bucket '{BUCKET_NAME}' não encontrado!")
            return False
            
    except Exception as e:
        print(f"❌ Erro na conexão: {str(e)}")
        return False

def test_upload_download():
    """Testa upload e download de um arquivo de teste"""
    try:
        print("\n📤 Testando upload/download...")
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        
        # Criar arquivo de teste temporário
        test_content = f"Teste de upload - {datetime.now().isoformat()}"
        test_filename = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as temp_file:
            temp_file.write(test_content)
            temp_file_path = temp_file.name
        
        try:
            # Upload do arquivo
            blob = bucket.blob(f"tests/{test_filename}")
            blob.upload_from_filename(temp_file_path)
            print(f"✅ Upload realizado: tests/{test_filename}")
            
            # Download do arquivo
            download_path = temp_file_path + "_downloaded"
            blob.download_to_filename(download_path)
            
            # Verificar conteúdo
            with open(download_path, 'r') as f:
                downloaded_content = f.read()
            
            if downloaded_content == test_content:
                print("✅ Download e verificação de conteúdo OK!")
                
                # Limpar arquivos de teste
                blob.delete()
                print("✅ Arquivo de teste removido do bucket")
                
                return True
            else:
                print("❌ Conteúdo do arquivo não confere!")
                return False
                
        finally:
            # Limpar arquivos temporários
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            if os.path.exists(download_path):
                os.unlink(download_path)
                
    except Exception as e:
        print(f"❌ Erro no teste de upload/download: {str(e)}")
        return False

def test_signed_urls():
    """Testa a geração de URLs assinadas"""
    try:
        print("\n🔗 Testando geração de URLs assinadas...")
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        
        test_blob_name = f"test_signed_url_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        blob = bucket.blob(test_blob_name)
        
        # Gerar URL assinada para upload
        upload_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.utcnow() + timedelta(hours=1),
            method="PUT"
        )
        
        # Gerar URL assinada para download
        download_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.utcnow() + timedelta(hours=1),
            method="GET"
        )
        
        print(f"✅ URL de upload gerada: {upload_url[:50]}...")
        print(f"✅ URL de download gerada: {download_url[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro na geração de URLs assinadas: {str(e)}")
        return False

def main():
    """Executa todos os testes"""
    print("🧪 === TESTE DE ACESSO AO GOOGLE CLOUD STORAGE ===")
    print(f"📦 Bucket: {BUCKET_NAME}")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 3
    
    # Teste 1: Conexão
    if test_gcs_connection():
        tests_passed += 1
    
    # Teste 2: Upload/Download
    if test_upload_download():
        tests_passed += 1
    
    # Teste 3: URLs assinadas
    if test_signed_urls():
        tests_passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 RESULTADO: {tests_passed}/{total_tests} testes passaram")
    
    if tests_passed == total_tests:
        print("🎉 Todos os testes passaram! GCS está funcionando corretamente.")
        return True
    else:
        print("⚠️  Alguns testes falharam. Verifique a configuração do GCS.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)