"""
BaseBot - Classe de base pour les bots
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from ..core.config import Config


class BaseBot(ABC):
    """Classe abstraite de base pour tous les bots"""

    def __init__(self, name: str):
        self.name = name
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def run(self, **kwargs):
        """Exécute le workflow complet du bot"""
        self.start_time = datetime.now()
        print("=" * 70)
        print(f"{self.name.upper()}")
        print("=" * 70)

        try:
            print(f"\n1. INITIALISATION")
            print("-" * 50)
            if not self.initialize():
                print("❌ Erreur d'initialisation")
                return None

            print(f"\n2. COLLECTE DES DONNEES")
            print("-" * 50)
            data = self.collect(**kwargs)
            if not data:
                print("⚠️ Aucune donnée collectée")

            print(f"\n3. ANALYSE")
            print("-" * 50)
            results = self.analyze(data, **kwargs)

            print(f"\n4. EXPORT")
            print("-" * 50)
            output_path = self.export(results, **kwargs)

            self.end_time = datetime.now()
            duration = (self.end_time - self.start_time).total_seconds()

            print("\n" + "=" * 70)
            print("RESUME")
            print("=" * 70)
            self.print_summary(data, results)
            print(f"\nDurée: {duration:.1f}s")
            print(f"Output: {output_path}")
            print("=" * 70)

            return results

        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            raise

    def initialize(self) -> bool:
        """Initialise les ressources"""
        Config.ensure_dirs()
        return True

    @abstractmethod
    def collect(self, **kwargs) -> Any:
        pass

    @abstractmethod
    def analyze(self, data: Any, **kwargs) -> Any:
        pass

    @abstractmethod
    def export(self, results: Any, **kwargs) -> Path:
        pass

    def print_summary(self, data: Any, results: Any):
        print(f"Données collectées: {len(data) if data else 0}")
        print(f"Résultats: {len(results) if results else 0}")
