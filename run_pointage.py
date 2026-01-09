#!/usr/bin/env python3
"""
Bot Pointage ZK BioTime → Odoo

Usage:
    python run_pointage.py              # Synchronisation unique
    python run_pointage.py daemon       # Mode daemon (toutes les 10 min)
    python run_pointage.py daemon 5     # Mode daemon (toutes les 5 min)
    python run_pointage.py test         # Teste les connexions
    python run_pointage.py cleanup      # Ferme les présences ouvertes > 24h
    python run_pointage.py cleanup 48   # Ferme les présences ouvertes > 48h
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.bots.pointage_bot import run_sync, run_daemon, test_connection, PointageBot


def cleanup_open_attendances(max_hours=24):
    """Ferme toutes les présences ouvertes de plus de X heures."""
    from datetime import datetime, timedelta
    from src.integrations.odoo import OdooClient

    print(f"Nettoyage des présences ouvertes de plus de {max_hours}h...")

    odoo = OdooClient()
    if not odoo.connect():
        print("Erreur connexion Odoo")
        return

    open_attendances = odoo.search_read(
        'hr.attendance',
        [('check_out', '=', False)],
        fields=['id', 'employee_id', 'check_in'],
        limit=500
    )

    print(f"  {len(open_attendances)} présences ouvertes trouvées")

    cutoff = datetime.now() - timedelta(hours=max_hours)
    closed = 0
    skipped = 0

    for att in open_attendances:
        try:
            check_in = datetime.strptime(att['check_in'], '%Y-%m-%d %H:%M:%S')

            if check_in < cutoff:
                check_out = (check_in + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                odoo.update_attendance_checkout(att['id'], check_out)
                emp_name = att['employee_id'][1] if att['employee_id'] else 'N/A'
                print(f"    Fermé: {emp_name} ({att['check_in']} → {check_out})")
                closed += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"    Erreur: {e}")

    print(f"\n  ✅ {closed} présences fermées, {skipped} récentes ignorées")


def main():
    if len(sys.argv) < 2:
        run_sync()
        return

    cmd = sys.argv[1].lower()

    if cmd == 'test':
        test_connection()

    elif cmd == 'daemon':
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else None
        run_daemon(interval)

    elif cmd == 'sync':
        run_sync()

    elif cmd == 'cleanup':
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        cleanup_open_attendances(hours)

    elif cmd in ['help', '-h', '--help']:
        print(__doc__)

    else:
        print(f"Commande inconnue: {cmd}")
        print(__doc__)


if __name__ == '__main__':
    main()
