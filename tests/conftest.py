"""
Configuração compartilhada dos testes.
Garante que o diretório raiz do projeto esteja no sys.path.
"""

import os
import sys

# Raiz do projeto (um nível acima de tests/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
