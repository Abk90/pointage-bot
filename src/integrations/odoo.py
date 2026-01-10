"""
Intégration Odoo - Module Présences (hr.attendance)
"""

import xmlrpc.client
from typing import List, Optional, Dict, Any
from difflib import SequenceMatcher

from ..core.config import Config


class OdooClient:
    """Client pour l'API Odoo XML-RPC"""

    def __init__(self):
        self.url = Config.ODOO_URL
        self.db = Config.ODOO_DB
        self.username = Config.ODOO_USER
        self.api_key = Config.ODOO_API_KEY
        self.uid = None
        self.models = None

    def connect(self) -> bool:
        """Établit la connexion à Odoo"""
        if not all([self.url, self.db, self.username, self.api_key]):
            print("  ⚠️ Configuration Odoo incomplète")
            return False

        try:
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = common.authenticate(self.db, self.username, self.api_key, {})

            if not self.uid:
                print("  ❌ Authentification Odoo échouée")
                return False

            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            return True

        except Exception as e:
            print(f"  ❌ Erreur connexion Odoo: {e}")
            return False

    def execute(self, model: str, method: str, *args, **kwargs) -> Any:
        """Exécute une méthode sur un modèle Odoo"""
        if not self.models or not self.uid:
            raise Exception("Non connecté à Odoo")

        return self.models.execute_kw(
            self.db, self.uid, self.api_key,
            model, method, list(args), kwargs
        )

    def search_read(
        self,
        model: str,
        domain: List,
        fields: List[str] = None,
        limit: int = None,
        offset: int = 0,
        order: str = None,
    ) -> List[Dict]:
        """Recherche et lit des enregistrements"""
        try:
            kwargs = {}
            if fields:
                kwargs['fields'] = fields
            if limit:
                kwargs['limit'] = limit
            if offset:
                kwargs['offset'] = offset
            if order:
                kwargs['order'] = order

            return self.execute(model, 'search_read', domain, **kwargs)

        except Exception as e:
            print(f"  ⚠️ Erreur search_read {model}: {e}")
            return []

    # ========== Méthodes pour Pointage (hr.attendance) ==========

    def get_employees(self, limit: int = 500) -> List[Dict]:
        """Récupère la liste des employés depuis Odoo"""
        try:
            employees = self.search_read(
                'hr.employee',
                [('active', '=', True)],
                fields=['id', 'name', 'barcode', 'department_id', 'work_email'],
                limit=limit
            )
            return employees

        except Exception as e:
            print(f"  ⚠️ Erreur récupération employés: {e}")
            return []

    def find_employee_by_badge(self, badge: str) -> Optional[Dict]:
        """Trouve un employé par son numéro de badge"""
        try:
            employees = self.search_read(
                'hr.employee',
                [('barcode', '=', str(badge)), ('active', '=', True)],
                fields=['id', 'name', 'barcode', 'department_id'],
                limit=1
            )
            return employees[0] if employees else None

        except Exception as e:
            print(f"  ⚠️ Erreur recherche employé badge: {e}")
            return None

    def find_employee_by_name(self, name: str, threshold: float = 0.85) -> Optional[Dict]:
        """Trouve un employé par son nom (fuzzy matching)"""
        try:
            employees = self.get_employees(limit=500)
            name_lower = name.lower().strip()

            best_match = None
            best_score = 0

            for emp in employees:
                emp_name = emp.get('name', '').lower().strip()
                score = SequenceMatcher(None, name_lower, emp_name).ratio()

                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = emp

            return best_match

        except Exception as e:
            print(f"  ⚠️ Erreur recherche employé nom: {e}")
            return None

    def get_open_attendance(self, employee_id: int) -> Optional[Dict]:
        """Récupère une présence ouverte (check-in sans check-out)"""
        try:
            attendances = self.search_read(
                'hr.attendance',
                [
                    ('employee_id', '=', employee_id),
                    ('check_out', '=', False),
                ],
                fields=['id', 'employee_id', 'check_in', 'check_out'],
                limit=1,
                order='check_in desc'
            )
            return attendances[0] if attendances else None

        except Exception as e:
            print(f"  ⚠️ Erreur récupération présence ouverte: {e}")
            return None

    def create_attendance_checkin(self, employee_id: int, check_in: str) -> Optional[int]:
        """Crée une entrée de présence (check-in)"""
        try:
            if 'T' in str(check_in):
                check_in = str(check_in).replace('T', ' ').split('+')[0].split('.')[0]

            vals = {
                'employee_id': employee_id,
                'check_in': check_in,
            }

            result = self.execute('hr.attendance', 'create', [vals])
            attendance_id = result[0] if isinstance(result, list) else result
            return attendance_id

        except Exception as e:
            print(f"  ⚠️ Erreur création check-in (emp={employee_id}, time={check_in}): {e}")
            return None

    def update_attendance_checkout(self, attendance_id: int, check_out: str) -> bool:
        """Met à jour une présence avec l'heure de sortie"""
        attendance_info = None
        try:
            if 'T' in str(check_out):
                check_out = str(check_out).replace('T', ' ').split('+')[0].split('.')[0]

            # Récupère les infos de la présence pour le debug
            attendance_info = self.search_read(
                'hr.attendance',
                [('id', '=', attendance_id)],
                fields=['id', 'employee_id', 'check_in', 'check_out'],
                limit=1
            )

            self.execute('hr.attendance', 'write', [attendance_id], {'check_out': check_out})
            return True

        except Exception as e:
            # Log détaillé avec les infos de la présence
            att_info = ""
            if attendance_info:
                att = attendance_info[0]
                emp_name = att['employee_id'][1] if att.get('employee_id') else 'N/A'
                att_info = f" [présence #{attendance_id}: {emp_name}, check_in={att.get('check_in')}]"
            print(f"  ⚠️ Erreur mise à jour check-out{att_info}: tentative check_out={check_out} → {e}")
            return False

    def check_checkin_exists(self, employee_id: int, timestamp: str, tolerance_minutes: int = 5) -> bool:
        """Vérifie si un check-in existe déjà à cette heure"""
        try:
            from datetime import datetime, timedelta

            if isinstance(timestamp, str):
                if 'T' in timestamp:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00').split('+')[0])
                else:
                    dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            else:
                dt = timestamp

            start = (dt - timedelta(minutes=tolerance_minutes)).strftime('%Y-%m-%d %H:%M:%S')
            end = (dt + timedelta(minutes=tolerance_minutes)).strftime('%Y-%m-%d %H:%M:%S')

            attendances = self.search_read(
                'hr.attendance',
                [
                    ('employee_id', '=', employee_id),
                    ('check_in', '>=', start),
                    ('check_in', '<=', end),
                ],
                fields=['id'],
                limit=1
            )

            return len(attendances) > 0

        except Exception as e:
            print(f"  ⚠️ Erreur vérification doublon check-in: {e}")
            return False

    def check_checkout_exists(self, employee_id: int, timestamp: str, tolerance_minutes: int = 5) -> bool:
        """Vérifie si un check-out existe déjà à cette heure"""
        try:
            from datetime import datetime, timedelta

            if isinstance(timestamp, str):
                if 'T' in timestamp:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00').split('+')[0])
                else:
                    dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            else:
                dt = timestamp

            start = (dt - timedelta(minutes=tolerance_minutes)).strftime('%Y-%m-%d %H:%M:%S')
            end = (dt + timedelta(minutes=tolerance_minutes)).strftime('%Y-%m-%d %H:%M:%S')

            attendances = self.search_read(
                'hr.attendance',
                [
                    ('employee_id', '=', employee_id),
                    ('check_out', '>=', start),
                    ('check_out', '<=', end),
                ],
                fields=['id'],
                limit=1
            )

            return len(attendances) > 0

        except Exception as e:
            print(f"  ⚠️ Erreur vérification doublon check-out: {e}")
            return False

    def check_attendance_exists(self, employee_id: int, check_in: str, tolerance_minutes: int = 5) -> bool:
        """Vérifie si une présence existe déjà pour éviter les doublons (legacy)"""
        return self.check_checkin_exists(employee_id, check_in, tolerance_minutes)

    def get_attendance_for_day(self, employee_id: int, date: str) -> Optional[Dict]:
        """Récupère la présence d'un employé pour une date donnée"""
        try:
            from datetime import datetime

            if isinstance(date, str):
                if ' ' in date:
                    date = date.split(' ')[0]
                day_start = f"{date} 00:00:00"
                day_end = f"{date} 23:59:59"
            else:
                day_start = date.strftime('%Y-%m-%d 00:00:00')
                day_end = date.strftime('%Y-%m-%d 23:59:59')

            attendances = self.search_read(
                'hr.attendance',
                [
                    ('employee_id', '=', employee_id),
                    ('check_in', '>=', day_start),
                    ('check_in', '<=', day_end),
                ],
                fields=['id', 'employee_id', 'check_in', 'check_out'],
                limit=1,
                order='check_in desc'
            )
            return attendances[0] if attendances else None

        except Exception as e:
            print(f"  ⚠️ Erreur récupération présence du jour: {e}")
            return None

    def get_next_attendance(self, employee_id: int, after_checkin: str) -> Optional[Dict]:
        """Récupère la présence suivante d'un employé après un check-in donné"""
        try:
            attendances = self.search_read(
                'hr.attendance',
                [
                    ('employee_id', '=', employee_id),
                    ('check_in', '>', after_checkin),
                ],
                fields=['id', 'employee_id', 'check_in', 'check_out'],
                limit=1,
                order='check_in asc'
            )
            return attendances[0] if attendances else None

        except Exception as e:
            print(f"  ⚠️ Erreur récupération présence suivante: {e}")
            return None

    def build_employee_badge_mapping(self) -> Dict[str, int]:
        """Construit un mapping badge -> employee_id"""
        employees = self.get_employees()
        return {
            str(emp.get('barcode')): emp['id']
            for emp in employees
            if emp.get('barcode')
        }
