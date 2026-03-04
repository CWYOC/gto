# gen_all_8max_cash_limp_math.py
# Generates "math-leaning" (pot-odds + rake) 8-max cash preflop charts WITH limps (SB).
#
# Output folder:
#   charts_matrix_8max_all_cash_limp_math/
#
# Use with your updated gto.py trainer:
#   python gen_all_8max_cash_limp_math.py
#   python gto.py --dir charts_matrix_8max_all_cash_limp_math
#
# Notes:
# - RFI_* spots: CALL = LIMP (so actions are RAISE/LIMP/FOLD)
# - VS_*_OPEN_* spots: RAISE = 3BET
# - RFI_*_VS_3BET_* spots: RAISE = 4BET
#
# This is NOT solver GTO, but it is more "real-world math-shaped" than the earlier heuristic:
# - Calls use pot odds + rake penalty
# - Strength uses Chen-style score -> equity proxy
# - 3bet/4bet are value + blocker bluffs with position-based targets

import csv
from pathlib import Path
from typing import Tuple

# ----------------------------
# Game config (edit to match your game)
# ----------------------------
POSITIONS = ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
POS_I = {p: i for i, p in enumerate(POSITIONS)}

OPEN_SIZE_BB = 2.5
THREEBET_SIZE_IP = 7.5
THREEBET_SIZE_OOP = 9.0
FOURBET_SIZE = 22.0  # not directly used for pot-odds here, but kept for future extension

RAKE_PCT = 0.05
RAKE_CAP_BB = 0.1

SB_LIMP_ENABLED = True

# ----------------------------
# Chart output
# ----------------------------
CHART_RANKS = "AKQJT98765432"
IDX = {r: i for i, r in enumerate(CHART_RANKS)}  # A=0 ... 2=12


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def fmt_cell(r: float, c: float, f: float) -> str:
    s = r + c + f
    if s <= 0:
        r, c, f = 0.0, 0.0, 1.0
        s = 1.0
    r, c, f = r / s, c / s, f / s
    return f"R{round(r*100)}/C{round(c*100)}/F{round(f*100)}"


def hand_label(r_row: str, r_col: str) -> str:
    """Matrix convention: diagonal pairs, above suited, below offsuit."""
    if r_row == r_col:
        return r_row + r_col
    row_i = IDX[r_row]
    col_i = IDX[r_col]
    if row_i < col_i:
        return f"{r_row}{r_col}s"
    hi = r_col if IDX[r_col] < IDX[r_row] else r_row
    lo = r_row if hi == r_col else r_col
    return f"{hi}{lo}o"


def rake_taken(pot_bb: float) -> float:
    return min(pot_bb * RAKE_PCT, RAKE_CAP_BB)


# ----------------------------
# Hand strength: Chen-ish
# ----------------------------
CHEN_BASE = {
    "A": 10, "K": 8, "Q": 7, "J": 6, "T": 5,
    "9": 4.5, "8": 4, "7": 3.5, "6": 3, "5": 2.5, "4": 2, "3": 1.5, "2": 1
}


def chen_score(lbl: str) -> float:
    if len(lbl) == 2:
        r = lbl[0]
        base = CHEN_BASE[r]
        score = base * 2
        if r in "AKQJT":
            score += 2
        elif r in "987":
            score += 1
        return max(score, 5.0)

    hi, lo, t = lbl[0], lbl[1], lbl[2]
    base = max(CHEN_BASE[hi], CHEN_BASE[lo])

    if t == "s":
        base += 2

    gap = abs(IDX[lo] - IDX[hi])
    if gap == 1:
        base += 1
    elif gap == 2:
        base -= 1
    elif gap == 3:
        base -= 2
    elif gap >= 4:
        base -= 4

    # small suited connector bonus
    if t == "s" and hi in "98765" and gap <= 2:
        base += 0.5

    return max(0.0, base)


def score_to_equity(score: float) -> float:
    """
    Map Chen-ish score to a rough equity proxy (NOT exact).
    Returns ~0.25..0.70
    """
    x = (score - 8.0) / 4.5
    eq = 0.45 + 0.18 * (x / (1 + abs(x)))
    return clamp01(eq)


def blockers(lbl: str) -> float:
    if len(lbl) == 2:
        return 0.2
    hi, lo = lbl[0], lbl[1]
    w = 0.0
    if hi == "A" or lo == "A":
        w += 1.0
    if hi == "K" or lo == "K":
        w += 0.6
    if hi == "Q" or lo == "Q":
        w += 0.3
    return w


def playability(lbl: str) -> float:
    if len(lbl) == 2:
        return 0.6
    hi, lo, t = lbl[0], lbl[1], lbl[2]
    gap = abs(IDX[lo] - IDX[hi])
    p = 0.0
    if t == "s":
        p += 0.6
    if gap == 1:
        p += 0.6
    elif gap == 2:
        p += 0.35
    elif gap == 3:
        p += 0.15
    if hi in "AKQJT" and lo in "AKQJT":
        p += 0.25
    return p


# ----------------------------
# Pot odds
# ----------------------------
def required_equity_call(call_bb: float, pot_before_call_bb: float) -> float:
    pot_after = pot_before_call_bb + call_bb
    req = call_bb / max(1e-9, pot_after)
    # rake penalty
    req += rake_taken(pot_after) / max(1e-9, pot_after)
    return clamp01(req)


def is_in_position(hero: str, villain: str) -> bool:
    return POS_I[hero] > POS_I[villain]


def target_3bet_pct(hero: str, opener: str) -> float:
    base = {
        "UTG": 0.03, "UTG1": 0.04, "LJ": 0.05, "HJ": 0.06,
        "CO": 0.08, "BTN": 0.11, "SB": 0.10, "BB": 0.07
    }.get(hero, 0.06)
    base += 0.03 * (POS_I[opener] / (len(POSITIONS) - 1))
    return clamp01(base)


def target_4bet_pct(opener: str, threebettor: str) -> float:
    base = 0.03
    if opener in ("CO", "BTN") and threebettor in ("SB", "BB"):
        base += 0.01
    return clamp01(base)


# ----------------------------
# Spot strategies
# ----------------------------
def freqs_rfi(lbl: str, pos: str) -> Tuple[float, float, float]:
    """
    RFI: (raise, limp, fold) encoded as (R, C, F)
    """
    s = chen_score(lbl)
    eq = score_to_equity(s)

    loose = {"UTG": 0.05, "UTG1": 0.10, "LJ": 0.18, "HJ": 0.28, "CO": 0.45, "BTN": 0.62, "SB": 0.58}.get(pos, 0.0)

    # Open threshold in equity space, loosen late
    thr = 0.49 - 0.09 * loose

    # Mix within band
    open_frac = clamp01((eq - (thr - 0.05)) / 0.10)
    if open_frac <= 0:
        return (0.0, 0.0, 1.0)

    limp = 0.0
    if pos == "SB" and SB_LIMP_ENABLED:
        p = playability(lbl)
        b = blockers(lbl)
        limp_pref = clamp01(0.55 * p - 0.25 * b)
        # avoid limping very strong hands
        limp_pref *= clamp01(1.0 - 1.4 * max(0.0, eq - 0.55))
        limp_share = clamp01(0.55 * limp_pref)
        limp = open_frac * limp_share

    raise_ = open_frac - limp
    fold = 1.0 - open_frac
    return (raise_, limp, fold)


def freqs_vs_open(lbl: str, hero: str, opener: str) -> Tuple[float, float, float]:
    """
    vs open: (3bet, call, fold) encoded as (R, C, F)
    """
    s = chen_score(lbl)
    eq = score_to_equity(s)

    ip = is_in_position(hero, opener)

    # Pot before hero acts: blinds 1.5 + opener size
    pot0 = 1.5 + OPEN_SIZE_BB
    call_cost = OPEN_SIZE_BB
    req_call = required_equity_call(call_cost, pot0)

    # Realization adjustment
    realization = 1.04 if ip else 0.95
    eq_eff = clamp01(eq * realization)

    # Call mixing band around required equity
    call_frac = clamp01((eq_eff - (req_call - 0.03)) / 0.08)

    # 3bet value + bluff using blockers, scaled to a target 3bet%
    tgt = target_3bet_pct(hero, opener)

    value_thr = 0.58 if ip else 0.60
    value = clamp01((eq - (value_thr - 0.03)) / 0.06)

    b = blockers(lbl)
    p = playability(lbl)
    bluff_seed = clamp01(0.55 * b + 0.15 * p - 0.55 * eq)
    bluff = bluff_seed * 0.35

    three_raw = clamp01(0.75 * value + 0.25 * bluff)
    three_frac = clamp01(three_raw * (tgt / 0.10))

    # Cap total continue and avoid double-counting
    cont = call_frac + three_frac
    if cont > 1.0:
        scale = 1.0 / cont
        call_frac *= scale
        three_frac *= scale
        cont = 1.0

    fold = 1.0 - cont
    return (three_frac, call_frac, fold)


def freqs_vs_3bet(lbl: str, opener: str, threebettor: str) -> Tuple[float, float, float]:
    """
    vs 3bet: (4bet, call, fold) encoded as (R, C, F)
    """
    s = chen_score(lbl)
    eq = score_to_equity(s)

    ip = is_in_position(opener, threebettor)  # opener has position if opener is later seat vs blinds etc.
    size3 = THREEBET_SIZE_IP if ip else THREEBET_SIZE_OOP

    pot0 = 1.5 + OPEN_SIZE_BB + size3
    call_cost = max(0.0, size3 - OPEN_SIZE_BB)
    req_call = required_equity_call(call_cost, pot0)

    realization = 1.02 if ip else 0.93
    eq_eff = clamp01(eq * realization)

    call_frac = clamp01((eq_eff - (req_call - 0.03)) / 0.08)

    tgt4 = target_4bet_pct(opener, threebettor)

    value_thr = 0.64
    value = clamp01((eq - (value_thr - 0.02)) / 0.05)

    b = blockers(lbl)
    bluff_seed = clamp01(0.70 * b - 0.85 * eq + 0.10 * playability(lbl))
    bluff = bluff_seed * (0.20 + (0.08 if threebettor in ("SB", "BB") else 0.0))

    four_raw = clamp01(0.85 * value + 0.15 * bluff)
    four_frac = clamp01(four_raw * (tgt4 / 0.04))

    cont = call_frac + four_frac
    if cont > 1.0:
        scale = 1.0 / cont
        call_frac *= scale
        four_frac *= scale
        cont = 1.0

    fold = 1.0 - cont
    return (four_frac, call_frac, fold)


# ----------------------------
# Writer
# ----------------------------
def write_matrix(spot: str, out_dir: Path, cell_func) -> Path:
    out_path = out_dir / f"{spot}_matrix.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([spot] + list(CHART_RANKS))
        for r_row in CHART_RANKS:
            row = [r_row]
            for r_col in CHART_RANKS:
                lbl = hand_label(r_row, r_col)
                r, c, fo = cell_func(lbl)
                row.append(f"{lbl}:{fmt_cell(r, c, fo)}")
            w.writerow(row)
    return out_path


def main():
    out_dir = Path("charts_matrix_8max_all_cash_limp_math")
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0

    # 1) RFI (exclude BB)
    for pos in POSITIONS:
        if pos == "BB":
            continue
        spot = f"RFI_{pos}"
        write_matrix(spot, out_dir, cell_func=lambda lbl, pos=pos: freqs_rfi(lbl, pos))
        written += 1

    # 2) VS OPEN
    for opener in POSITIONS:
        if opener == "BB":
            continue
        for hero in POSITIONS:
            if POS_I[hero] <= POS_I[opener]:
                continue
            spot = f"VS_{opener}_OPEN_{hero}"
            write_matrix(spot, out_dir, cell_func=lambda lbl, hero=hero, opener=opener: freqs_vs_open(lbl, hero, opener))
            written += 1

    # 3) VS 3BET after opening
    for opener in POSITIONS:
        if opener == "BB":
            continue
        for threebettor in POSITIONS:
            if POS_I[threebettor] <= POS_I[opener]:
                continue
            spot = f"RFI_{opener}_VS_3BET_{threebettor}"
            write_matrix(spot, out_dir, cell_func=lambda lbl, opener=opener, threebettor=threebettor: freqs_vs_3bet(lbl, opener, threebettor))
            written += 1

    (out_dir / "README.txt").write_text(
        "Math-leaning baseline charts (NOT solver-GTO)\n\n"
        "Key ideas used:\n"
        "- Chen-style hand strength -> rough equity proxy\n"
        "- Calls use pot-odds + rake penalty\n"
        "- 3bet and 4bet are value + blocker bluffs, with target frequencies by position\n"
        "- RFI spots include SB limps (CALL in RFI = LIMP)\n\n"
        "Spot interpretation for your trainer:\n"
        "  RFI_*               -> RAISE / LIMP / FOLD  (LIMP stored as CALL)\n"
        "  VS_*_OPEN_*         -> 3BET / CALL / FOLD   (3BET stored as RAISE)\n"
        "  RFI_*_VS_3BET_*     -> 4BET / CALL / FOLD   (4BET stored as RAISE)\n",
        encoding="utf-8"
    )

    print(f"Done. Wrote {written} matrices to: {out_dir.resolve()}")
    print("Run trainer with:")
    print("  python gto.py --dir charts_matrix_8max_all_cash_limp_math")


if __name__ == "__main__":
    main()