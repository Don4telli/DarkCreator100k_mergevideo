# Configuração do Gunicorn para Cloud Run
import multiprocessing

# Bind
bind = "0.0.0.0:8080"

# Workers
workers = 1  # Para processamento de vídeo, usar apenas 1 worker para evitar conflitos
worker_class = "sync"
worker_connections = 1000

# Timeouts
timeout = 3600  # 1 hora para processamento de vídeo
keepalive = 2

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "darkcreator100k-mergevideo"

# Memory and resource limits
max_requests = 100
max_requests_jitter = 10
preload_app = True