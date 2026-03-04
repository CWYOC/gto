import csv
import random
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List

RANKS = "23456789TJQKA"
RANK_TO_I = {r: i for i, r in enumerate(RANKS)}
CHART_RANKS = "AKQJT98765432"  # matrix order

ACTIONS = ("RAISE", "CALL", "FOLD")


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
    # Pairs first (AA..22)
    for r in reversed(RANKS):
        labels.append(r + r)
    # Non-pairs hi>lo, suited then offsuit
    for i in range(len(RANKS) - 1, -1, -1):
        hi = RANKS[i]
        for j in range(i - 1, -1, -1):
            lo = RANKS[j]
            labels.append(f"{hi}{lo}s")
            labels.append(f"{hi}{lo}o")
    return labels


ALL_169 = all_169_labels()


def normalize_hand_label(lbl: str) -> str:
    """
    Normalize labels like 'qko' -> 'KQo', 'aqs' -> 'AQs', 'aa' -> 'AA'
    Returns canonical: pairs 'AA', suited 'AKs', offsuit 'AKo'
    """
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
                # If you left blank, default to fold=1
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
    Accepts common cell payload formats, examples:
      "R70/C30/F0"
      "R0.7/C0.3/F0"
      "R__/C__/F__"  -> treated as blanks => fold 1
      ""             -> fold 1
    Returns normalized (r,c,f).
    """
    s = (cell_payload or "").strip()
    if not s or "__" in s:
        return (0.0, 0.0, 1.0)

    # Extract numbers after R, C, F
    # Allow percentages or decimals.
    def find(prefix: str) -> float:
        m = re.search(rf"{prefix}\s*([0-9]*\.?[0-9]+)", s, re.IGNORECASE)
        return float(m.group(1)) if m else 0.0

    r = find("R")
    c = find("C")
    f = find("F")

    total = r + c + f
    if total <= 0:
        return (0.0, 0.0, 1.0)

    # If user typed 70/30/0 (sum 100), normalization handles it.
    return (r / total, c / total, f / total)


def hand_label_from_matrix(r_row: str, r_col: str) -> str:
    """
    Same convention as your matrix generator:
      diagonal -> pair
      above diagonal -> suited
      below diagonal -> offsuit
    """
    if r_row == r_col:
        return r_row + r_col

    row_i = CHART_RANKS.index(r_row)
    col_i = CHART_RANKS.index(r_col)

    if row_i < col_i:
        # above diagonal -> suited (row rank first)
        return normalize_hand_label(f"{r_row}{r_col}s")
    else:
        # below diagonal -> offsuit (higher rank first)
        return normalize_hand_label(f"{r_col}{r_row}o")


def load_matrix_csv(path: Path) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    """
    Matrix CSV format:
      First row header: [spot, A, K, Q, ... 2]
      First col each row: rank letter
      Each cell: "AKs:R70/C30/F0" or "AKs:R__/C__/F__" etc.
    Returns:
      chart[spot][hand_label] = (raise, call, fold)
    """
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows or len(rows[0]) < 2:
        raise ValueError(f"{path.name} doesn't look like a matrix CSV")

    spot = (rows[0][0] or "").strip()
    if not spot:
        # fallback: infer from filename
        spot = path.stem.replace("_matrix", "")

    header_ranks = [c.strip() for c in rows[0][1:]]
    if "".join(header_ranks) != CHART_RANKS:
        # Still allow if header ranks are correct set/order
        # but best to use the generator's default.
        pass

    chart: Dict[str, Dict[str, Tuple[float, float, float]]] = {spot: {}}

    # rows[1:] each starts with row-rank
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
            # Expected "AKs:payload"
            m = CELL_RE.match(cell_text)
            if m:
                hand_lbl_raw = m.group(1)
                payload = m.group(2)
                hand_lbl = normalize_hand_label(hand_lbl_raw)
                freqs = parse_freq_triplet(payload)
            else:
                # If the cell isn't in "HAND:..." format, infer hand from position
                hand_lbl = hand_label_from_matrix(r_row, r_col)
                freqs = parse_freq_triplet(cell_text)

            chart[spot][hand_lbl] = freqs

    # Ensure every hand exists; missing defaults to fold
    for h in ALL_169:
        chart[spot].setdefault(h, (0.0, 0.0, 1.0))

    return chart


# -------------------------
# Merge multiple sources
# -------------------------
def merge_charts(*charts: Dict[str, Dict[str, Tuple[float, float, float]]]) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    out: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    for ch in charts:
        for spot, hands in ch.items():
            out.setdefault(spot, {})
            out[spot].update(hands)
    return out


# -------------------------
# Trainer logic
# -------------------------
def sample_action(freqs: Tuple[float, float, float]) -> str:
    r, c, f = freqs
    x = random.random()
    if x < r:
        return "RAISE"
    if x < r + c:
        return "CALL"
    return "FOLD"


def explain(freqs: Tuple[float, float, float]) -> str:
    r, c, f = freqs
    return f"Target mix: RAISE {r:.0%} | CALL {c:.0%} | FOLD {f:.0%}"


def load_all_from_folder(folder: Path) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    """
    Loads:
      - charts.csv (row-based) if present
      - any *_matrix.csv in folder (matrix-based)
    """
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


def main():
    print("=== GTO Table Trainer (8-max friendly, CSV-driven) ===")
    print("Loads YOUR tables (row CSV and/or matrix CSV) and quizzes you with mixed-frequency actions.\n")
    print("Files supported in current folder:")
    print("  - charts.csv (row format: spot,hand,raise,call,fold)")
    print("  - *_matrix.csv (13x13 readable grid format)")
    print("\nCommands:")
    print("  q            quit")
    print("  spots        list available spots")
    print("  spot <name>  lock a spot (e.g., spot RFI_UTG)")
    print("  unlock       unlock spot (random spot each hand)")
    print("  show         show frequencies for the current question again")
    print("  any key      next question\n")

    folder = Path(".")
    try:
        chart = load_all_from_folder(folder)
    except Exception as e:
        print(f"Load error: {e}")
        return

    spots = sorted(chart.keys())
    print(f"Loaded {len(spots)} spot(s). Type 'spots' to list.\n")

    locked_spot: Optional[str] = None
    score = 0
    total = 0
    last_info = None  # (spot, hand, freqs)

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
                s, h, freqs = last_info
                print(f"Spot: {s} | Hand: {h}")
                print(explain(freqs))
            else:
                print("No previous question yet.")
            continue

        # Ask a new question
        spot = locked_spot or random.choice(spots)
        hand = random.choice(list(chart[spot].keys()))
        freqs = chart[spot][hand]
        target = sample_action(freqs)
        last_info = (spot, hand, freqs)

        print(f"\nSpot: {spot}")
        print(f"Hand: {hand}")
        print("Choose: RAISE / CALL / FOLD")
        ans = input("action> ").strip().upper()

        if ans not in ACTIONS:
            print("Invalid. Use RAISE/CALL/FOLD.")
            continue

        total += 1
        if ans == target:
            score += 1
            print("✅ Correct (for this mixed-frequency draw).")
        else:
            print(f"❌ Not this time. The sampled GTO action was: {target}")

        print(explain(freqs))
        print(f"Score: {score}/{total} ({(score/total)*100:.1f}%)")

    print(f"\nFinal: {score}/{total} ({(score/total)*100:.1f}%)")


if __name__ == "__main__":
    main()