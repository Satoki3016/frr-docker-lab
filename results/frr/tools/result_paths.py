"""分類後も既存の実験タグを使えるようにする、解析用のパス解決。

フォルダ名の規則は YYYYMMDD_結果_目的_条件_連番 (結果は running / success / fail)。
結果語を省いた名前 (例: 20260925_unplug_wcmp_01) でも、該当するフォルダが1つなら解決する。
"""
import re
from pathlib import Path

RESULTS_ROOT = Path(__file__).resolve().parent.parent
_RESULT = re.compile(r"^(\d{8})_(?:running|success|fail)_(.+)$")


def strip_result(name: str) -> str:
    """'20260925_success_x_01' → '20260925_x_01'。結果語が無ければそのまま。"""
    m = _RESULT.match(name)
    return f"{m.group(1)}_{m.group(2)}" if m else name


def result_dir(tag: str) -> Path:
    path = Path(tag)
    direct = path if path.is_absolute() else RESULTS_ROOT / path
    if direct.is_dir():
        return direct
    if len(path.parts) == 1 or (path.is_absolute() and path.parent == RESULTS_ROOT):
        for key in (lambda p: p.name == path.name,
                    lambda p: strip_result(p.name) == strip_result(path.name)):
            matches = [p for p in RESULTS_ROOT.rglob(path.name[:8] + "*") if p.is_dir() and key(p)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ValueError(f"同名の実験があります。分類からの相対パスを指定してください: {matches}")
    raise FileNotFoundError(f"実験が見つかりません: {tag} (results/frr/README.md を参照)")
