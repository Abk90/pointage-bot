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
    python run_pointage.py fix          # Corrige les présences corrompues (check_in = check_out)
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


def fix_corrupted_attendances(days_back=7):
    """Corrige les présences corrompues où check_in = check_out."""
    from datetime import datetime, timedelta
    from src.integrations.odoo import OdooClient

    print(f"Recherche des présences corrompues (check_in = check_out) des {days_back} derniers jours...")

    odoo = OdooClient()
    if not odoo.connect():
        print("Erreur connexion Odoo")
        return

    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d 00:00:00')

    attendances = odoo.search_read(
        'hr.attendance',
        [('check_in', '>=', start_date)],
        fields=['id', 'employee_id', 'check_in', 'check_out'],
        order='check_in asc'
    )

    # Trouver les présences corrompues
    corrupted = []
    for att in attendances:
        if att.get('check_in') and att.get('check_out') and att['check_in'] == att['check_out']:
            corrupted.append(att)

    print(f"  {len(corrupted)} présences corrompues trouvées sur {len(attendances)} total\n")

    if not corrupted:
        print("  ✅ Aucune présence corrompue à corriger")
        return

    fixed = 0
    deleted = 0
    errors = 0

    # Grouper par employé pour détecter les doublons
    by_employee = {}
    for att in corrupted:
        emp_id = att['employee_id'][0] if att.get('employee_id') else None
        if emp_id:
            if emp_id not in by_employee:
                by_employee[emp_id] = []
            by_employee[emp_id].append(att)

    for emp_id, emp_attendances in by_employee.items():
        emp_name = emp_attendances[0]['employee_id'][1] if emp_attendances[0].get('employee_id') else 'N/A'

        if len(emp_attendances) == 1:
            # Une seule présence corrompue → réouvrir (supprimer check_out)
            att = emp_attendances[0]
            try:
                odoo.execute('hr.attendance', 'write', [att['id']], {'check_out': False})
                print(f"  ✅ {emp_name}: ID {att['id']} réouverte ({att['check_in']})")
                fixed += 1
            except Exception as e:
                print(f"  ❌ {emp_name}: ID {att['id']} erreur - {e}")
                errors += 1
        else:
            # Plusieurs présences corrompues → garder la première, supprimer les autres
            # Trier par check_in
            sorted_atts = sorted(emp_attendances, key=lambda x: x['check_in'])

            # Réouvrir la première
            first = sorted_atts[0]
            try:
                odoo.execute('hr.attendance', 'write', [first['id']], {'check_out': False})
                print(f"  ✅ {emp_name}: ID {first['id']} réouverte ({first['check_in']})")
                fixed += 1
            except Exception as e:
                print(f"  ❌ {emp_name}: ID {first['id']} erreur - {e}")
                errors += 1

            # Supprimer les autres (doublons)
            for att in sorted_atts[1:]:
                try:
                    odoo.execute('hr.attendance', 'unlink', [att['id']])
                    print(f"  🗑️  {emp_name}: ID {att['id']} supprimée (doublon)")
                    deleted += 1
                except Exception as e:
                    print(f"  ❌ {emp_name}: ID {att['id']} erreur suppression - {e}")
                    errors += 1

    print(f"\n  Résumé:")
    print(f"    ✅ {fixed} présences réouvertes")
    print(f"    🗑️  {deleted} doublons supprimés")
    print(f"    ❌ {errors} erreurs")


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

    elif cmd == 'fix':
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        fix_corrupted_attendances(days)

    elif cmd in ['help', '-h', '--help']:
        print(__doc__)

    else:
        print(f"Commande inconnue: {cmd}")
        print(__doc__)


if __name__ == '__main__':
    main()
