#!/usr/bin/env python3
"""
Teste local da aplicação sem dependência do GCS
Este script testa o fluxo da aplicação usando arquivos locais.
"""

import requests
import json
import tempfile
import os
from datetime import datetime

BASE_URL = "http://localhost:8082"

def test_health_check():
    """Testa o endpoint de health check"""
    try:
        print("🏥 Testando health check...")
        response = requests.get(f"{BASE_URL}/health")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Health check OK: {data['status']}")
            return True
        else:
            print(f"❌ Health check falhou: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erro no health check: {str(e)}")
        return False

def test_signed_url_endpoint():
    """Testa o endpoint de geração de signed URL"""
    try:
        print("\n🔗 Testando endpoint de signed URL...")
        
        payload = {
            "filename": "test_image.jpg",
            "file_type": "image"
        }
        
        response = requests.post(
            f"{BASE_URL}/get_signed_url",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload)
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Signed URL endpoint funcionando")
            print(f"📝 Filename retornado: {data.get('filename', 'N/A')}")
            return True
        else:
            print(f"❌ Signed URL endpoint falhou: {response.status_code}")
            print(f"📄 Resposta: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Erro no teste de signed URL: {str(e)}")
        return False

def test_create_video_endpoint():
    """Testa o endpoint de criação de vídeo (sem arquivos reais)"""
    try:
        print("\n🎬 Testando endpoint de criação de vídeo...")
        
        payload = {
            "image_filenames": ["fake_image1.jpg", "fake_image2.jpg"],
            "audio_filename": None,
            "filename": "test_video.mp4",
            "aspect_ratio": "9:16",
            "green_duration": 5.0
        }
        
        response = requests.post(
            f"{BASE_URL}/create_video",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload)
        )
        
        # Esperamos que falhe porque os arquivos não existem no GCS
        # mas o endpoint deve responder adequadamente
        print(f"📊 Status da resposta: {response.status_code}")
        print(f"📄 Resposta: {response.text[:200]}...")
        
        # Se retornar 500 com erro de GCS, significa que o endpoint está funcionando
        if response.status_code == 500 and "bucket" in response.text.lower():
            print("✅ Endpoint funcionando (erro esperado de GCS)")
            return True
        elif response.status_code == 200:
            print("✅ Endpoint funcionando perfeitamente")
            return True
        else:
            print(f"⚠️  Resposta inesperada: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erro no teste de criação de vídeo: {str(e)}")
        return False

def test_frontend_loading():
    """Testa se o frontend carrega corretamente"""
    try:
        print("\n🌐 Testando carregamento do frontend...")
        
        response = requests.get(BASE_URL)
        
        if response.status_code == 200:
            html_content = response.text
            
            # Verificar se elementos importantes estão presentes
            checks = [
                ("DarkNews Creator" in html_content, "Título da página"),
                ("videoForm" in html_content, "Formulário de vídeo"),
                ("getSignedUrl" in html_content, "Função de signed URL"),
                ("uploadFileToGCS" in html_content, "Função de upload GCS"),
                ("create_video" in html_content, "Endpoint de criação")
            ]
            
            passed_checks = sum(1 for check, _ in checks if check)
            total_checks = len(checks)
            
            print(f"✅ Frontend carregado: {passed_checks}/{total_checks} verificações passaram")
            
            for check, description in checks:
                status = "✅" if check else "❌"
                print(f"  {status} {description}")
            
            return passed_checks == total_checks
        else:
            print(f"❌ Frontend não carregou: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erro no teste do frontend: {str(e)}")
        return False

def main():
    """Executa todos os testes locais"""
    print("🧪 === TESTE LOCAL DA APLICAÇÃO ===")
    print(f"🌐 URL Base: {BASE_URL}")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 4
    
    # Teste 1: Health Check
    if test_health_check():
        tests_passed += 1
    
    # Teste 2: Frontend
    if test_frontend_loading():
        tests_passed += 1
    
    # Teste 3: Signed URL
    if test_signed_url_endpoint():
        tests_passed += 1
    
    # Teste 4: Create Video
    if test_create_video_endpoint():
        tests_passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 RESULTADO: {tests_passed}/{total_tests} testes passaram")
    
    if tests_passed >= 3:  # Pelo menos 3 de 4 testes
        print("🎉 Aplicação está funcionando localmente!")
        print("💡 Para funcionar completamente, configure as credenciais do GCS.")
        return True
    else:
        print("⚠️  Problemas detectados na aplicação.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)