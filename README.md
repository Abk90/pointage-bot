# Bot Pointage ZK BioTime → Odoo

Synchronise automatiquement les pointages de ZK BioTime vers Odoo (module Présences).

## Installation

### 1. Installer Python
Télécharger sur https://www.python.org/downloads/
**Important** : Cocher "Add Python to PATH" pendant l'installation.

### 2. Télécharger le projet
```bash
git clone https://github.com/Abk90/pointage-bot.git
cd pointage-bot
```

Ou télécharger le ZIP depuis GitHub.

### 3. Installer les dépendances
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Configurer
Copier `.env.example` en `.env` et remplir les informations.

### 5. Tester
```bash
python run_pointage.py test
```

### 6. Lancer
```bash
python run_pointage.py daemon
```

## Commandes

| Commande | Description |
|----------|-------------|
| `python run_pointage.py` | Sync unique |
| `python run_pointage.py daemon` | Mode continu (toutes les 10 min) |
| `python run_pointage.py daemon 5` | Mode continu (toutes les 5 min) |
| `python run_pointage.py test` | Teste les connexions |
| `python run_pointage.py cleanup` | Ferme les présences ouvertes > 24h |

## Démarrage automatique Windows

1. Appuyer sur `Win + R`
2. Taper `shell:startup` et Entrée
3. Copier `start_pointage.bat` dans ce dossier
