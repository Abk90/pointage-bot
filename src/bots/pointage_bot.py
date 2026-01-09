"""
PointageBot - Synchronisation ZK BioTime → Odoo
Extrait les pointages de la pointeuse et les intègre dans hr.attendance
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from .base_bot import BaseBot
from ..core.config import Config
from ..integrations.odoo import OdooClient
from ..integrations.zkbiotime import ZKBioTimeClient, Pointage


@dataclass
class SyncResult:
    """Résultat de synchronisation pour un pointage"""
    pointage: Pointage
    employee_id_zk: str
    employee_id_odoo: Optional[int]
    employee_name: str
    action: str  # 'checkin', 'checkout', 'skipped', 'error'
    attendance_id: Optional[int] = None
    error: Optional[str] = None


@dataclass
class SyncStats:
    """Statistiques de synchronisation"""
    total_pointages: int = 0
    checkins_created: int = 0
    checkouts_updated: int = 0
    skipped_duplicates: int = 0
    skipped_no_match: int = 0
    errors: int = 0


class PointageBot(BaseBot):
    """
    Bot de synchronisation des pointages.
    ZK BioTime → Odoo hr.attendance
    """

    def __init__(self):
        super().__init__("PointageBot - Synchronisation Pointages")
        self.zk_client: Optional[ZKBioTimeClient] = None
        self.odoo_client: Optional[OdooClient] = None
        self.badge_mapping: Dict[str, int] = {}
        self.name_mapping: Dict[str, int] = {}
        self.stats = SyncStats()

        self.data_dir = Config.DATA_DIR / "pointage"
        self.sync_log_file = self.data_dir / "sync_log.json"
        self.mapping_file = self.data_dir / "employee_mapping.json"

    def initialize(self) -> bool:
        """Initialise les connexions ZK BioTime et Odoo"""
        Config.ensure_dirs()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        print("  Connexion à Odoo...")
        self.odoo_client = OdooClient()
        if not self.odoo_client.connect():
            print("  ❌ Impossible de se connecter à Odoo")
            return False
        print("  ✅ Connecté à Odoo")

        print("  Connexion à ZK BioTime...")
        self.zk_client = ZKBioTimeClient()
        if not self.zk_client.connect():
            print("  ❌ Impossible de se connecter à ZK BioTime")
            return False

        print("  Chargement du mapping employés...")
        self._load_or_build_mapping()
        print(f"  ✅ {len(self.badge_mapping)} employés mappés par badge")

        return True

    def _load_or_build_mapping(self):
        """Charge le mapping employés depuis le cache ou le reconstruit"""
        if self.mapping_file.exists():
            try:
                with open(self.mapping_file, 'r') as f:
                    data = json.load(f)
                    self.badge_mapping = data.get('badge_mapping', {})
                    self.name_mapping = data.get('name_mapping', {})

                    last_update = data.get('last_update')
                    if last_update:
                        last_dt = datetime.fromisoformat(last_update)
                        if datetime.now() - last_dt < timedelta(days=1):
                            return
            except:
                pass

        self._build_mapping()

    def _build_mapping(self):
        """Construit le mapping entre employés ZK BioTime et Odoo"""
        print("  Construction du mapping employés...")

        odoo_employees = self.odoo_client.get_employees()
        print(f"    {len(odoo_employees)} employés Odoo")

        self.badge_mapping = {}
        for emp in odoo_employees:
            badge = emp.get('barcode')
            if badge:
                self.badge_mapping[str(badge)] = emp['id']

        self.name_mapping = {
            emp.get('name', '').lower().strip(): emp['id']
            for emp in odoo_employees
            if emp.get('name')
        }

        zk_employees = self.zk_client.get_employees()
        print(f"    {len(zk_employees)} employés ZK BioTime")

        unmatched = []
        for zk_emp in zk_employees:
            badge = str(zk_emp.get('badge_number', zk_emp.get('id', '')))
            name = zk_emp.get('name', '')

            if badge not in self.badge_mapping and name.lower().strip() not in self.name_mapping:
                unmatched.append(f"{name} (badge: {badge})")

        if unmatched:
            print(f"    ⚠️ {len(unmatched)} employés ZK non trouvés dans Odoo:")
            for u in unmatched[:5]:
                print(f"      - {u}")
            if len(unmatched) > 5:
                print(f"      ... et {len(unmatched) - 5} autres")

        self._save_mapping()

    def _save_mapping(self):
        """Sauvegarde le mapping dans un fichier"""
        try:
            with open(self.mapping_file, 'w') as f:
                json.dump({
                    'badge_mapping': self.badge_mapping,
                    'name_mapping': self.name_mapping,
                    'last_update': datetime.now().isoformat(),
                }, f, indent=2)
        except Exception as e:
            print(f"  ⚠️ Erreur sauvegarde mapping: {e}")

    def collect(self, start_date: datetime = None, end_date: datetime = None, **kwargs) -> List[Pointage]:
        """Collecte les pointages depuis ZK BioTime."""
        print(f"  Récupération des pointages depuis ZK BioTime...")

        # Par défaut, récupère les pointages d'aujourd'hui
        if not start_date:
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        pointages = self.zk_client.get_attendances(
            start_date=start_date,
            end_date=end_date,
        )

        print(f"  ✅ {len(pointages)} pointages récupérés")

        # Trie par timestamp
        pointages.sort(key=lambda p: p.timestamp)

        return pointages

    def analyze(self, pointages: List[Pointage], **kwargs) -> List[SyncResult]:
        """Analyse et synchronise les pointages vers Odoo."""
        results = []
        self.stats = SyncStats(total_pointages=len(pointages))

        # Groupe les pointages par employé
        pointages_by_employee = {}
        for p in pointages:
            if p.employee_id not in pointages_by_employee:
                pointages_by_employee[p.employee_id] = []
            pointages_by_employee[p.employee_id].append(p)

        print(f"  Traitement de {len(pointages)} pointages pour {len(pointages_by_employee)} employés...")

        for emp_id, emp_pointages in pointages_by_employee.items():
            odoo_emp_id = self._find_odoo_employee(emp_id, emp_pointages[0].employee_name)

            if not odoo_emp_id:
                self.stats.skipped_no_match += len(emp_pointages)
                for p in emp_pointages:
                    results.append(SyncResult(
                        pointage=p,
                        employee_id_zk=emp_id,
                        employee_id_odoo=None,
                        employee_name=p.employee_name,
                        action='skipped',
                        error='Employé non trouvé dans Odoo',
                    ))
                continue

            # Traite les pointages triés par timestamp
            sorted_pointages = sorted(emp_pointages, key=lambda p: p.timestamp)

            for pointage in sorted_pointages:
                result = self._process_pointage(pointage, odoo_emp_id)
                results.append(result)

        return results

    def _find_odoo_employee(self, zk_emp_id: str, zk_emp_name: str) -> Optional[int]:
        """Trouve l'ID employé Odoo correspondant"""
        if zk_emp_id in self.badge_mapping:
            return self.badge_mapping[zk_emp_id]

        name_lower = zk_emp_name.lower().strip()
        if name_lower in self.name_mapping:
            return self.name_mapping[name_lower]

        emp = self.odoo_client.find_employee_by_name(zk_emp_name, threshold=0.85)
        if emp:
            self.name_mapping[name_lower] = emp['id']
            return emp['id']

        return None

    def _process_pointage(self, pointage: Pointage, odoo_emp_id: int) -> SyncResult:
        """
        Traite un pointage individuel.

        Logique simplifiée :
        - Si présence ouverte → le pointage est une SORTIE
        - Si pas de présence ouverte → le pointage est une ENTRÉE
        """
        try:
            timestamp_str = pointage.timestamp.strftime('%Y-%m-%d %H:%M:%S')

            # Vérifie si ce pointage existe déjà (doublon)
            if self.odoo_client.check_attendance_exists(odoo_emp_id, timestamp_str, tolerance_minutes=2):
                self.stats.skipped_duplicates += 1
                return SyncResult(
                    pointage=pointage,
                    employee_id_zk=pointage.employee_id,
                    employee_id_odoo=odoo_emp_id,
                    employee_name=pointage.employee_name,
                    action='skipped',
                    error='Doublon détecté',
                )

            # Vérifie s'il y a une présence ouverte
            open_attendance = self.odoo_client.get_open_attendance(odoo_emp_id)

            if open_attendance:
                # Il y a une présence ouverte → c'est une SORTIE
                # Vérifie que le checkout est après le checkin
                open_checkin_str = open_attendance.get('check_in', '')
                try:
                    open_checkin = datetime.strptime(open_checkin_str, '%Y-%m-%d %H:%M:%S')
                except:
                    open_checkin = datetime.min

                if pointage.timestamp <= open_checkin:
                    # Le pointage est AVANT ou ÉGAL au check-in → ignorer
                    self.stats.skipped_no_match += 1
                    return SyncResult(
                        pointage=pointage,
                        employee_id_zk=pointage.employee_id,
                        employee_id_odoo=odoo_emp_id,
                        employee_name=pointage.employee_name,
                        action='skipped',
                        error=f'Pointage antérieur au check-in ({open_checkin_str})',
                    )

                # Ferme la présence avec l'heure du pointage
                success = self.odoo_client.update_attendance_checkout(
                    attendance_id=open_attendance['id'],
                    check_out=timestamp_str,
                )

                if success:
                    self.stats.checkouts_updated += 1
                    print(f"    ✅ Sortie: {pointage.employee_name} à {timestamp_str}")
                    return SyncResult(
                        pointage=pointage,
                        employee_id_zk=pointage.employee_id,
                        employee_id_odoo=odoo_emp_id,
                        employee_name=pointage.employee_name,
                        action='checkout',
                        attendance_id=open_attendance['id'],
                    )
                else:
                    self.stats.errors += 1
                    return SyncResult(
                        pointage=pointage,
                        employee_id_zk=pointage.employee_id,
                        employee_id_odoo=odoo_emp_id,
                        employee_name=pointage.employee_name,
                        action='error',
                        error='Erreur mise à jour check-out',
                    )

            else:
                # Pas de présence ouverte → c'est une ENTRÉE
                attendance_id = self.odoo_client.create_attendance_checkin(
                    employee_id=odoo_emp_id,
                    check_in=timestamp_str,
                )

                if attendance_id:
                    self.stats.checkins_created += 1
                    print(f"    ✅ Entrée: {pointage.employee_name} à {timestamp_str}")
                    return SyncResult(
                        pointage=pointage,
                        employee_id_zk=pointage.employee_id,
                        employee_id_odoo=odoo_emp_id,
                        employee_name=pointage.employee_name,
                        action='checkin',
                        attendance_id=attendance_id,
                    )
                else:
                    self.stats.errors += 1
                    return SyncResult(
                        pointage=pointage,
                        employee_id_zk=pointage.employee_id,
                        employee_id_odoo=odoo_emp_id,
                        employee_name=pointage.employee_name,
                        action='error',
                        error='Erreur création check-in',
                    )

        except Exception as e:
            self.stats.errors += 1
            return SyncResult(
                pointage=pointage,
                employee_id_zk=pointage.employee_id,
                employee_id_odoo=odoo_emp_id,
                employee_name=pointage.employee_name,
                action='error',
                error=str(e),
            )

    def export(self, results: List[SyncResult], **kwargs) -> Path:
        """Exporte le log de synchronisation."""
        self.zk_client.save_last_sync()

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'stats': asdict(self.stats),
            'results': [
                {
                    'employee_name': r.employee_name,
                    'employee_id_zk': r.employee_id_zk,
                    'employee_id_odoo': r.employee_id_odoo,
                    'timestamp': r.pointage.timestamp.isoformat(),
                    'punch_type': r.pointage.punch_type,
                    'action': r.action,
                    'attendance_id': r.attendance_id,
                    'error': r.error,
                }
                for r in results
            ],
        }

        log_data = []
        if self.sync_log_file.exists():
            try:
                with open(self.sync_log_file, 'r') as f:
                    log_data = json.load(f)
                    log_data = log_data[-99:]
            except:
                pass

        log_data.append(log_entry)

        with open(self.sync_log_file, 'w') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

        print(f"  ✅ Log sauvegardé: {self.sync_log_file}")

        return self.sync_log_file

    def print_summary(self, data: Any, results: Any):
        """Affiche le résumé de synchronisation"""
        print(f"\nStatistiques:")
        print(f"  Total pointages traités: {self.stats.total_pointages}")
        print(f"  ✅ Check-ins créés: {self.stats.checkins_created}")
        print(f"  ✅ Check-outs mis à jour: {self.stats.checkouts_updated}")
        print(f"  ⏭️ Doublons ignorés: {self.stats.skipped_duplicates}")
        print(f"  ⚠️ Non matchés/ignorés: {self.stats.skipped_no_match}")
        print(f"  ❌ Erreurs: {self.stats.errors}")


def run_sync(start_date: datetime = None, end_date: datetime = None):
    """Lance une synchronisation manuelle."""
    bot = PointageBot()
    return bot.run(start_date=start_date, end_date=end_date)


def run_daemon(interval_minutes: int = None):
    """Lance le bot en mode daemon (synchronisation continue)."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    interval = interval_minutes or Config.ZK_SYNC_INTERVAL_MINUTES

    print("=" * 70)
    print("POINTAGE BOT - MODE DAEMON")
    print("=" * 70)
    print(f"Synchronisation toutes les {interval} minutes")
    print("Appuyez sur Ctrl+C pour arrêter")
    print("=" * 70)

    scheduler = BlockingScheduler()

    def sync_job():
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Lancement sync...")
        try:
            bot = PointageBot()
            bot.run()
        except Exception as e:
            print(f"❌ Erreur sync: {e}")

    scheduler.add_job(sync_job, 'interval', minutes=interval, next_run_time=datetime.now())

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nArrêt du daemon...")
        scheduler.shutdown()


def test_connection():
    """Teste les connexions ZK BioTime et Odoo"""
    print("=" * 70)
    print("TEST DE CONNEXION")
    print("=" * 70)

    print("\n1. Test ZK BioTime")
    print("-" * 50)
    zk = ZKBioTimeClient()
    zk_result = zk.test_connection()
    print(f"   Status: {zk_result['status']}")
    print(f"   Mode: {zk_result['mode']}")
    print(f"   Message: {zk_result['message']}")

    print("\n2. Test Odoo")
    print("-" * 50)
    odoo = OdooClient()
    if odoo.connect():
        employees = odoo.get_employees(limit=5)
        print(f"   ✅ Connecté à Odoo")
        print(f"   {len(employees)} employés trouvés (affichage limité à 5)")
        for emp in employees[:5]:
            print(f"      - {emp['name']} (badge: {emp.get('barcode', 'N/A')})")
    else:
        print("   ❌ Impossible de se connecter à Odoo")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == 'test':
            test_connection()
        elif cmd == 'daemon':
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else None
            run_daemon(interval)
        elif cmd == 'sync':
            run_sync()
        else:
            print(f"Commande inconnue: {cmd}")
            print("Usage: python -m src.bots.pointage_bot [test|sync|daemon [interval_minutes]]")
    else:
        run_sync()
