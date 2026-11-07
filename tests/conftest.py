import os

# Testy nie zapisują bazy na dysku (chyba że test sam poda ścieżkę).
os.environ.setdefault("NEXUS_DB_PATH", ":memory:")
