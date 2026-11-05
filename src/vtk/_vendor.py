"""Um só ponto de entrada para a skill de terceiros (vendor/dev-video-editing, sem modificações).

    from vtk._vendor import ev   # módulo scripts/edit_video.py

Funções internas usadas por nós (se a skill for atualizada, conferir que continuam iguais: tests/test_vendor_contract.py):
ver USED abaixo.
"""
import importlib.util, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "vendor/dev-video-editing/scripts/edit_video.py")

_spec = importlib.util.spec_from_file_location("edit_video", PATH)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

USED = ["mark", "plan_spans", "zoom_plan", "apply_replace", "stamp", "probe", "audio_energy",
        "visual_events", "check_tools", "WARNINGS", "EYE_LINE"]
