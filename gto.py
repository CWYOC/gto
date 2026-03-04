import csv
import random
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List

RANKS = "23456789TJQKA"
RANK_TO_I = {r: i for i, r in enumerate(RANKS)}
CHART_RANKS = "AKQJT98765432"  # matrix order

# Internal action keys (canonical)
A_RAISE = "RAISE"
A_CALL = "CALL"
A_FOLD = "FOLD"
ACTIONS_INTERNAL = (A_RAISE, A_CALL, A_FOLD)


# -------------------------
# Hand + normalization
# -------------------------
@dataclass(frozen=True)
class Hand:
    r1: str
    r2: str
    suited: Optional[bool]  # True suited, False offsuit, None pair

    def label(self) -> str:
        a, b = self.r1, self.r2
        if a == b:
            return a + a
        hi, lo = (a, b) if RANK_TO_I[a] > RANK_TO_I[b] else (b, a)
        return f"{hi}{lo}{'s' if self.suited else 'o'}"


def all_169_labels() -> List[str]:
    labels = []
    # Pairs AA..22
    for r in reversed(RANKS):
        labels.append(r + r)
    # Non-pairs hi>lo: suited then offsuit
    for i in range(len(RANKS) - 1, -1, -1):
        hi = RANKS[i]
        for j in range(i - 1, -1, -1):
            lo = RANKS[j]
            labels.append(f"{hi}{lo}s")
            labels.append(f"{hi}{lo}o")
    return labels


ALL_169 = all_169_labels()


def normalize_hand_label(lbl: str) -> str:
    """Normalize labels like 'qko' -> 'KQo', 'aqs' -> 'AQs', 'aa' -> 'AA'."""
    lbl = (lbl or "").strip()
    if not lbl:
        raise ValueError("Empty hand label")
    lbl = lbl.upper()

    if len(lbl) == 2:
        if lbl[0] != lbl[1] or lbl[0] not in RANKS:
            raise ValueError(f"Bad pair label: {lbl}")
        return lbl

    if len(lbl) == 3 and lbl[0] in RANKS and lbl[1] in RANKS and lbl[2] in ("S", "O"):
        a, b, t = lbl[0], lbl[1], lbl[2].lower()
        if a == b:
            return a + a
        hi, lo = (a, b) if RANK_TO_I[a] > RANK_TO_I[b] else (b, a)
        return f"{hi}{lo}{t}"

    raise ValueError(f"Bad hand label: {lbl}")


# -------------------------
# Loading charts (row-based)
# -------------------------
def load_row_csv(path: Path) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    """
    Row CSV format:
      spot,hand,raise,call,fold
    Returns:
      chart[spot][hand_label] = (raise, call, fold) normalized
    """
    chart: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"spot", "hand", "raise", "call", "fold"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"{path.name} must have columns: {sorted(required)}")

        for row in reader:
            spot = (row.get("spot") or "").strip()
            if not spot:
                continue

            hand = normalize_hand_label(row.get("hand") or "")

            def to_float(x: str) -> float:
                x = (x or "").strip()
                if x == "":
                    return 0.0
                return float(x)

            rf = to_float(row.get("raise", "0"))
            cf = to_float(row.get("call", "0"))
            ff = to_float(row.get("fold", "0"))

            s = rf + cf + ff
            if s <= 0:
                # default fold if blank
                rf, cf, ff = 0.0, 0.0, 1.0
                s = 1.0

            rf, cf, ff = rf / s, cf / s, ff / s
            chart.setdefault(spot, {})[hand] = (rf, cf, ff)

    return chart


# -------------------------
# Loading charts (matrix-based)
# -------------------------
CELL_RE = re.compile(r"^\s*([AKQJT98765432]{2}(?:[so])?)\s*:\s*(.*)\s*$", re.IGNORECASE)

def parse_freq_triplet(cell_payload: str) -> Tuple[float, float, float]:
    """
    Accepts:
      "R70/C30/F0"
      "R0.7/C0.3/F0"
      "R70%/C30%/F0%"  (percent signs OK)
      "" or placeholders -> fold 1
    Returns normalized (r,c,f).
    """
    s = (cell_payload or "").strip()
    if not s or "__" in s:
        return (0.0, 0.0, 1.0)

    # Extract numbers after R, C, F (allow optional %)
    def find(prefix: str) -> float:
        m = re.search(rf"{prefix}\s*([0-9]*\.?[0-9]+)\s*%?", s, re.IGNORECASE)
        return float(m.group(1)) if m else 0.0

    r = find("R")
    c = find("C")
    f = find("F")

    total = r + c + f
    if total <= 0:
        return (0.0, 0.0, 1.0)

    return (r / total, c / total, f / total)


def hand_label_from_matrix(r_row: str, r_col: str) -> str:
    """Infer label from matrix coordinates (diagonal/pair, above/suited, below/offsuit)."""
    if r_row == r_col:
        return r_row + r_col

    row_i = CHART_RANKS.index(r_row)
    col_i = CHART_RANKS.index(r_col)

    if row_i < col_i:
        return normalize_hand_label(f"{r_row}{r_col}s")
    else:
        return normalize_hand_label(f"{r_col}{r_row}o")


def load_matrix_csv(path: Path) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    """
    Matrix CSV:
      header: [spot, A, K, ..., 2]
      each cell: "AKs:R70/C30/F0"
    Returns:
      chart[spot][hand] = (raise, call, fold)
    """
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows or len(rows[0]) < 2:
        raise ValueError(f"{path.name} doesn't look like a matrix CSV")

    spot = (rows[0][0] or "").strip() or path.stem.replace("_matrix", "")
    chart: Dict[str, Dict[str, Tuple[float, float, float]]] = {spot: {}}

    for r in rows[1:]:
        if not r:
            continue
        r_row = (r[0] or "").strip()
        if r_row not in CHART_RANKS:
            continue

        cells = r[1:]
        for j, cell in enumerate(cells):
            if j >= len(CHART_RANKS):
                break
            r_col = CHART_RANKS[j]

            cell_text = (cell or "").strip()
            m = CELL_RE.match(cell_text)
            if m:
                hand_lbl = normalize_hand_label(m.group(1))
                payload = m.group(2)
                freqs = parse_freq_triplet(payload)
            else:
                hand_lbl = hand_label_from_matrix(r_row, r_col)
                freqs = parse_freq_triplet(cell_text)

            chart[spot][hand_lbl] = freqs

    # ensure all hands exist (default fold)
    for h in ALL_169:
        chart[spot].setdefault(h, (0.0, 0.0, 1.0))

    return chart


def merge_charts(*charts: Dict[str, Dict[str, Tuple[float, float, float]]]) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    out: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    for ch in charts:
        for spot, hands in ch.items():
            out.setdefault(spot, {})
            out[spot].update(hands)
    return out


def load_all_from_folder(folder: Path) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    charts = []

    row_file = folder / "charts.csv"
    if row_file.exists():
        charts.append(load_row_csv(row_file))

    for p in sorted(folder.glob("*_matrix.csv")):
        charts.append(load_matrix_csv(p))

    if not charts:
        raise FileNotFoundError(
            f"No charts found in {folder.resolve()}.\n"
            f"Put charts.csv or *_matrix.csv files there."
        )

    return merge_charts(*charts)


# -------------------------
# Spot-aware action labels
# -------------------------
def spot_action_aliases(spot: str) -> Tuple[str, str, str]:
    """
    Returns display labels for (RAISE, CALL, FOLD) depending on spot type.

    - RFI_*                      : (RAISE, LIMP, FOLD)
    - VS_*_OPEN_*                : (3BET, CALL, FOLD)
    - RFI_*_VS_3BET_*            : (4BET, CALL, FOLD)
    Default                      : (RAISE, CALL, FOLD)
    """
    s = spot.upper()
    if s.startswith("RFI_") and "_VS_3BET_" not in s:
        return ("RAISE", "LIMP", "FOLD")
    if "_VS_3BET_" in s:
        return ("4BET", "CALL", "FOLD")
    if s.startswith("VS_") and "_OPEN_" in s:
        return ("3BET", "CALL", "FOLD")
    return ("RAISE", "CALL", "FOLD")


def display_to_internal(spot: str, user_action: str) -> Optional[str]:
    """Map user displayed action back to internal action key."""
    user_action = user_action.strip().upper()
    a_raise, a_call, a_fold = spot_action_aliases(spot)
    mapping = {
        a_raise: A_RAISE,
        a_call: A_CALL,
        a_fold: A_FOLD,
        # allow internal words too
        "RAISE": A_RAISE,
        "CALL": A_CALL,
        "FOLD": A_FOLD,
        "LIMP": A_CALL,
        "3BET": A_RAISE,
        "4BET": A_RAISE,
    }
    return mapping.get(user_action)


def internal_to_display(spot: str, internal_action: str) -> str:
    a_raise, a_call, a_fold = spot_action_aliases(spot)
    if internal_action == A_RAISE:
        return a_raise
    if internal_action == A_CALL:
        return a_call
    return a_fold


# -------------------------
# Trainer core
# -------------------------
def sample_action(freqs: Tuple[float, float, float]) -> str:
    r, c, f = freqs
    x = random.random()
    if x < r:
        return A_RAISE
    if x < r + c:
        return A_CALL
    return A_FOLD


def explain(spot: str, freqs: Tuple[float, float, float]) -> str:
    r, c, f = freqs
    a_raise, a_call, a_fold = spot_action_aliases(spot)
    return f"Target mix: {a_raise} {r:.0%} | {a_call} {c:.0%} | {a_fold} {f:.0%}"


def main():
    print("=== GTO Trainer (8-max cash + limp aware) ===")
    print("Loads your *_matrix.csv files and quizzes actions with mixed frequencies.")
    print("Interpretation depends on spot:\n"
          "  RFI_*               -> RAISE / LIMP / FOLD  (LIMP stored as CALL)\n"
          "  VS_*_OPEN_*         -> 3BET / CALL / FOLD   (3BET stored as RAISE)\n"
          "  RFI_*_VS_3BET_*     -> 4BET / CALL / FOLD   (4BET stored as RAISE)\n")

    folder = Path(".")
    try:
        chart = load_all_from_folder(folder)
    except Exception as e:
        print(f"Load error: {e}")
        return

    spots = sorted(chart.keys())
    print(f"Loaded {len(spots)} spot(s). Type 'spots' to list.\n")

    print("Commands:")
    print("  q            quit")
    print("  spots        list spots")
    print("  spot <name>  lock one spot")
    print("  unlock       random spots")
    print("  show         show last target mix\n")

    locked_spot: Optional[str] = None
    score = 0
    total = 0
    last_info = None  # (spot, hand, freqs, sampled_internal_action)

    while True:
        cmd = input("> ").strip()
        low = cmd.lower()

        if low == "q":
            break
        if low == "spots":
            print("\n".join(spots))
            continue
        if low.startswith("spot "):
            name = cmd[5:].strip()
            if name in chart:
                locked_spot = name
                print(f"Locked spot: {locked_spot}")
            else:
                print("Unknown spot. Type 'spots' to see available.")
            continue
        if low == "unlock":
            locked_spot = None
            print("Unlocked (random spots).")
            continue
        if low == "show":
            if last_info:
                s, h, freqs, sampled = last_info
                print(f"Spot: {s} | Hand: {h}")
                print(explain(s, freqs))
                print(f"(Last sampled action: {internal_to_display(s, sampled)})")
            else:
                print("No previous question yet.")
            continue

        # new question
        spot = locked_spot or random.choice(spots)
        hand = random.choice(list(chart[spot].keys()))
        freqs = chart[spot][hand]
        sampled_internal = sample_action(freqs)

        a_raise, a_call, a_fold = spot_action_aliases(spot)
        print(f"\nSpot: {spot}")
        print(f"Hand: {hand}")
        print(f"Choose: {a_raise} / {a_call} / {a_fold}")
        ans = input("action> ").strip()

        internal = display_to_internal(spot, ans)
        if internal is None:
            print("Invalid action for this spot.")
            continue

        total += 1
        if internal == sampled_internal:
            score += 1
            print("✅ Correct (for this mixed-frequency draw).")
        else:
            print(f"❌ Not this time. Sampled action was: {internal_to_display(spot, sampled_internal)}")

        print(explain(spot, freqs))
        print(f"Score: {score}/{total} ({(score/total)*100:.1f}%)")

        last_info = (spot, hand, freqs, sampled_internal)

    print(f"\nFinal: {score}/{total} ({(score/total)*100:.1f}%)")


if __name__ == "__main__":
    main()