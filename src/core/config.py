"""
Configuration centralisée - Variables d'environnement
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration centralisée du projet"""

    # Chemins
    BASE_DIR = Path(__file__).parent.parent.parent
    DATA_DIR = BASE_DIR / "data"

    # Odoo
    ODOO_URL = os.getenv("ODOO_URL")
    ODOO_DB = os.getenv("ODOO_DB")
    ODOO_USER = os.getenv("ODOO_USER")
    ODOO_API_KEY = os.getenv("ODOO_API_KEY")

    # ZK BioTime (Pointage)
    ZK_BIOTIME_URL = os.getenv("ZK_BIOTIME_URL")
    ZK_BIOTIME_USERNAME = os.getenv("ZK_BIOTIME_USERNAME")
    ZK_BIOTIME_PASSWORD = os.getenv("ZK_BIOTIME_PASSWORD")
    ZK_DEVICE_IP = os.getenv("ZK_DEVICE_IP")
    ZK_DEVICE_PORT = int(os.getenv("ZK_DEVICE_PORT", "4370"))
    ZK_SYNC_INTERVAL_MINUTES = int(os.getenv("ZK_SYNC_INTERVAL_MINUTES", "10"))

    @classmethod
    def ensure_dirs(cls):
        """Crée les dossiers nécessaires"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (cls.DATA_DIR / "pointage").mkdir(parents=True, exist_ok=True)
