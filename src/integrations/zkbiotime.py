"""
Client ZK BioTime - Extraction des pointages
Supporte:
- API REST ZK BioTime 7.x/8.x
- Connexion directe à la pointeuse via pyzk (fallback)
"""

import json
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

from ..core.config import Config


@dataclass
class Pointage:
    """Représente un pointage (entrée ou sortie)"""
    employee_id: str  # ID/Badge de l'employé
    employee_name: str
    timestamp: datetime
    punch_type: str  # 'IN' ou 'OUT'
    device_id: Optional[str] = None
    device_name: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'timestamp': self.timestamp.isoformat(),
        }


class ZKBioTimeClient:
    """
    Client pour ZK BioTime.
    Détecte automatiquement le mode de connexion disponible.
    """

    def __init__(self):
        self.biotime_url = Config.ZK_BIOTIME_URL
        self.username = Config.ZK_BIOTIME_USERNAME
        self.password = Config.ZK_BIOTIME_PASSWORD
        self.device_ip = Config.ZK_DEVICE_IP
        self.device_port = Config.ZK_DEVICE_PORT

        self.session = requests.Session()
        self.token = None
        self.connection_mode = None  # 'api' ou 'direct'

        # Cache du dernier sync
        self.last_sync_file = Config.DATA_DIR / "pointage" / "last_sync.json"

    def connect(self) -> bool:
        """
        Établit la connexion. Essaie l'API REST d'abord, puis le mode direct.

        Returns:
            True si connexion réussie
        """
        # Essaie l'API REST d'abord
        if self.biotime_url and self.username and self.password:
            if self._connect_api():
                self.connection_mode = 'api'
                print(f"  ✅ Connecté à ZK BioTime API ({self.biotime_url})")
                return True

        # Fallback: connexion directe à la pointeuse
        if self.device_ip:
            if self._connect_direct():
                self.connection_mode = 'direct'
                print(f"  ✅ Connecté directement à la pointeuse ({self.device_ip})")
                return True

        print("  ❌ Impossible de se connecter à ZK BioTime")
        print("     Vérifiez ZK_BIOTIME_URL ou ZK_DEVICE_IP dans .env")
        return False

    def _connect_api(self) -> bool:
        """Connexion via API REST ZK BioTime"""
        try:
            # ZK BioTime 8.x utilise /api-token-auth/
            # ZK BioTime 7.x utilise /jwt-api-token-auth/
            endpoints = [
                '/api-token-auth/',
                '/jwt-api-token-auth/',
                '/api/v1/auth/login/',
            ]

            for endpoint in endpoints:
                try:
                    url = f"{self.biotime_url.rstrip('/')}{endpoint}"
                    response = self.session.post(
                        url,
                        json={'username': self.username, 'password': self.password},
                        timeout=10
                    )

                    if response.status_code == 200:
                        data = response.json()
                        self.token = data.get('token') or data.get('access_token') or data.get('Token')
                        if self.token:
                            self.session.headers['Authorization'] = f'Token {self.token}'
                            return True
                except:
                    continue

            return False

        except Exception as e:
            print(f"  ⚠️ Erreur connexion API: {e}")
            return False

    def _connect_direct(self) -> bool:
        """Connexion directe à la pointeuse via pyzk"""
        try:
            from zk import ZK

            zk = ZK(self.device_ip, port=self.device_port, timeout=5)
            conn = zk.connect()
            conn.disconnect()
            return True

        except ImportError:
            print("  ⚠️ Module pyzk non installé (pip install pyzk)")
            return False
        except Exception as e:
            print(f"  ⚠️ Erreur connexion directe: {e}")
            return False

    def get_employees(self) -> List[Dict]:
        """
        Récupère la liste des employés.

        Returns:
            Liste des employés avec id, name, badge_number
        """
        if self.connection_mode == 'api':
            return self._get_employees_api()
        else:
            return self._get_employees_direct()

    def _get_employees_api(self) -> List[Dict]:
        """Récupère les employés via API"""
        try:
            # ZK BioTime 8.x
            endpoints = [
                '/personnel/api/employees/',
                '/api/v1/personnel/employee/',
                '/iclock/api/employees/',
            ]

            for endpoint in endpoints:
                try:
                    url = f"{self.biotime_url.rstrip('/')}{endpoint}"
                    response = self.session.get(url, timeout=30)

                    if response.status_code == 200:
                        data = response.json()
                        employees = data if isinstance(data, list) else data.get('data', data.get('results', []))

                        return [
                            {
                                'id': str(emp.get('emp_code') or emp.get('id') or emp.get('badge_number')),
                                'name': emp.get('first_name', '') + ' ' + emp.get('last_name', '') if emp.get('first_name') else emp.get('name', ''),
                                'badge_number': str(emp.get('emp_code') or emp.get('badge_number') or emp.get('id')),
                                'department': emp.get('department', {}).get('name') if isinstance(emp.get('department'), dict) else emp.get('department'),
                            }
                            for emp in employees
                        ]
                except:
                    continue

            return []

        except Exception as e:
            print(f"  ⚠️ Erreur récupération employés API: {e}")
            return []

    def _get_employees_direct(self) -> List[Dict]:
        """Récupère les employés directement depuis la pointeuse"""
        try:
            from zk import ZK

            zk = ZK(self.device_ip, port=self.device_port, timeout=5)
            conn = zk.connect()

            users = conn.get_users()
            employees = [
                {
                    'id': str(user.user_id),
                    'name': user.name,
                    'badge_number': str(user.user_id),
                    'department': None,
                }
                for user in users
            ]

            conn.disconnect()
            return employees

        except Exception as e:
            print(f"  ⚠️ Erreur récupération employés direct: {e}")
            return []

    def get_attendances(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        employee_ids: List[str] = None,
    ) -> List[Pointage]:
        """
        Récupère les pointages.

        Args:
            start_date: Date de début (défaut: dernier sync ou 7 jours)
            end_date: Date de fin (défaut: maintenant)
            employee_ids: Liste d'IDs d'employés à filtrer

        Returns:
            Liste de Pointage
        """
        if not end_date:
            end_date = datetime.now()

        if not start_date:
            # Charge la date du dernier sync ou 7 jours par défaut
            start_date = self._get_last_sync_date() or (end_date - timedelta(days=7))

        if self.connection_mode == 'api':
            return self._get_attendances_api(start_date, end_date, employee_ids)
        else:
            return self._get_attendances_direct(start_date, end_date, employee_ids)

    def _get_attendances_api(
        self,
        start_date: datetime,
        end_date: datetime,
        employee_ids: List[str] = None,
    ) -> List[Pointage]:
        """Récupère les pointages via API avec pagination"""
        pointages = []

        try:
            # ZK BioTime 8.x endpoints
            endpoints = [
                '/iclock/api/transactions/',
                '/api/v1/attendance/transaction/',
                '/att/api/attRecord/',
            ]

            for endpoint in endpoints:
                try:
                    url = f"{self.biotime_url.rstrip('/')}{endpoint}"
                    page = 1
                    page_size = 100  # Récupère 100 résultats par page
                    all_records = []

                    while True:
                        params = {
                            'start_time': start_date.strftime('%Y-%m-%d %H:%M:%S'),
                            'end_time': end_date.strftime('%Y-%m-%d %H:%M:%S'),
                            'page': page,
                            'page_size': page_size,
                        }

                        response = self.session.get(url, params=params, timeout=60)

                        if response.status_code != 200:
                            break

                        data = response.json()

                        # Gère différents formats de réponse
                        if isinstance(data, list):
                            records = data
                        else:
                            records = data.get('data', data.get('results', []))

                        if not records:
                            break

                        all_records.extend(records)

                        # Vérifie s'il y a plus de pages
                        total = data.get('count', 0) if isinstance(data, dict) else len(records)
                        if len(all_records) >= total or len(records) < page_size:
                            break

                        page += 1

                    if all_records:
                        records = all_records

                        for record in records:
                            emp_id = str(record.get('emp_code') or record.get('employee_id') or record.get('pin'))

                            # Filtre par employé si spécifié
                            if employee_ids and emp_id not in employee_ids:
                                continue

                            # Parse la date/heure
                            timestamp_str = record.get('punch_time') or record.get('att_time') or record.get('timestamp')
                            try:
                                if 'T' in str(timestamp_str):
                                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                else:
                                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            except:
                                continue

                            # Détermine le type (entrée/sortie)
                            punch_state = record.get('punch_state') or record.get('status') or record.get('state', 0)

                            # punch_state = 255 signifie auto-détection
                            # On stocke 'AUTO' et le bot déterminera IN/OUT selon l'ordre
                            if int(punch_state) == 255:
                                punch_type = 'AUTO'
                            elif int(punch_state) in [0, 4]:  # 0=Check-In, 4=OT-In
                                punch_type = 'IN'
                            else:  # 1=Check-Out, 2=Break-Out, 3=Break-In, 5=OT-Out
                                punch_type = 'OUT'

                            # Récupère le nom de l'employé
                            emp_name = record.get('first_name', '') + ' ' + record.get('last_name', '')
                            emp_name = emp_name.strip() or record.get('emp_name') or record.get('employee_name') or ''

                            pointages.append(Pointage(
                                employee_id=emp_id,
                                employee_name=emp_name,
                                timestamp=timestamp,
                                punch_type=punch_type,
                                device_id=str(record.get('terminal_sn') or record.get('terminal_id') or record.get('device_id') or ''),
                                device_name=record.get('terminal_alias') or record.get('terminal_name') or record.get('device_name'),
                            ))

                        break  # Endpoint trouvé, on sort

                except Exception as e:
                    continue

            return pointages

        except Exception as e:
            print(f"  ⚠️ Erreur récupération pointages API: {e}")
            return []

    def _get_attendances_direct(
        self,
        start_date: datetime,
        end_date: datetime,
        employee_ids: List[str] = None,
    ) -> List[Pointage]:
        """Récupère les pointages directement depuis la pointeuse"""
        pointages = []

        try:
            from zk import ZK

            zk = ZK(self.device_ip, port=self.device_port, timeout=30)
            conn = zk.connect()

            # Récupère tous les pointages
            attendances = conn.get_attendance()

            # Récupère les noms des utilisateurs
            users = {str(u.user_id): u.name for u in conn.get_users()}

            for att in attendances:
                # Filtre par date
                if att.timestamp < start_date or att.timestamp > end_date:
                    continue

                emp_id = str(att.user_id)

                # Filtre par employé si spécifié
                if employee_ids and emp_id not in employee_ids:
                    continue

                # Détermine le type (entrée/sortie)
                # Status: 0=Check-In, 1=Check-Out, 2=Break-Out, 3=Break-In, 4=OT-In, 5=OT-Out
                punch_type = 'IN' if att.status in [0, 3, 4] else 'OUT'

                pointages.append(Pointage(
                    employee_id=emp_id,
                    employee_name=users.get(emp_id, ''),
                    timestamp=att.timestamp,
                    punch_type=punch_type,
                    device_id=self.device_ip,
                ))

            conn.disconnect()
            return pointages

        except Exception as e:
            print(f"  ⚠️ Erreur récupération pointages direct: {e}")
            return []

    def _get_last_sync_date(self) -> Optional[datetime]:
        """Récupère la date du dernier sync"""
        try:
            if self.last_sync_file.exists():
                with open(self.last_sync_file, 'r') as f:
                    data = json.load(f)
                    return datetime.fromisoformat(data['last_sync'])
        except:
            pass
        return None

    def save_last_sync(self, sync_date: datetime = None):
        """Sauvegarde la date du dernier sync"""
        try:
            self.last_sync_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.last_sync_file, 'w') as f:
                json.dump({
                    'last_sync': (sync_date or datetime.now()).isoformat(),
                }, f)
        except Exception as e:
            print(f"  ⚠️ Erreur sauvegarde last_sync: {e}")

    def test_connection(self) -> Dict[str, Any]:
        """
        Teste la connexion et retourne des infos de diagnostic.

        Returns:
            Dict avec status, mode, employees_count, etc.
        """
        result = {
            'status': 'error',
            'mode': None,
            'employees_count': 0,
            'message': '',
        }

        if not self.connect():
            result['message'] = 'Connexion impossible'
            return result

        result['mode'] = self.connection_mode

        employees = self.get_employees()
        result['employees_count'] = len(employees)

        if employees:
            result['status'] = 'ok'
            result['message'] = f'Connexion réussie ({self.connection_mode}), {len(employees)} employés trouvés'
            result['sample_employees'] = employees[:3]
        else:
            result['status'] = 'warning'
            result['message'] = 'Connexion OK mais aucun employé trouvé'

        return result
