import csv
from pathlib import Path
from typing import Tuple

# ----------------------------
# Config
# ----------------------------
CHART_RANKS = "AKQJT98765432"
IDX = {r: i for i, r in enumerate(CHART_RANKS)}  # A=0 ... 2=12

POSITIONS_8MAX = ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
POS_I = {p: i for i, p in enumerate(POSITIONS_8MAX)}

# Limp policy knobs (cash)
# - SB limping is the main realistic limp node in cash.
# - If you want *only* SB limps, set BTN_LIMP_ENABLED = False, CO_LIMP_ENABLED = False
SB_LIMP_ENABLED = True
BTN_LIMP_ENABLED = False
CO_LIMP_ENABLED = False

# ----------------------------
# Helpers: hand label in matrix
# ----------------------------
def hand_label(r_row: str, r_col: str) -> str:
    """13x13 chart convention:
       diagonal -> pair (AA)
       above diagonal -> suited (AKs)
       below diagonal -> offsuit (AKo)
    """
    if r_row == r_col:
        return r_row + r_col
    row_i = IDX[r_row]
    col_i = IDX[r_col]
    if row_i < col_i:  # above diagonal
        return f"{r_row}{r_col}s"
    else:  # below diagonal
        hi = r_col if IDX[r_col] < IDX[r_row] else r_row
        lo = r_row if hi == r_col else r_col
        return f"{hi}{lo}o"

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def fmt_cell(r: float, c: float, f: float) -> str:
    s = r + c + f
    if s <= 0:
        r, c, f = 0.0, 0.0, 1.0
        s = 1.0
    r, c, f = r / s, c / s, f / s
    return f"R{round(r*100)}/C{round(c*100)}/F{round(f*100)}"

def rank_strength(r: str) -> float:
    # A=1.0 ... 2~0.0
    return 1.0 - (IDX[r] / 12.0)

# ----------------------------
# Base hand scoring (0..1-ish)
# ----------------------------
def score_pair(r: str) -> float:
    s = rank_strength(r)
    return clamp01(0.55 + 0.45 * s)

def score_suited(hi: str, lo: str) -> float:
    hi_s = rank_strength(hi)
    lo_s = rank_strength(lo)
    gap = abs(IDX[lo] - IDX[hi])  # 1=connector
    base = 0.35 * hi_s + 0.25 * lo_s

    if hi == "A":
        base += 0.25
    if hi in "AKQJT" and lo in "AKQJT":
        base += 0.15

    if gap == 1:
        base += 0.20
    elif gap == 2:
        base += 0.12
    elif gap == 3:
        base += 0.06

    return clamp01(base)

def score_offsuit(hi: str, lo: str) -> float:
    hi_s = rank_strength(hi)
    lo_s = rank_strength(lo)
    gap = abs(IDX[lo] - IDX[hi])
    base = 0.30 * hi_s + 0.18 * lo_s

    if hi == "A":
        base += 0.16
    if hi in "AKQJT" and lo in "AKQJT":
        base += 0.10

    base -= 0.05 * max(0, gap - 2)
    return clamp01(base)

def hand_score(lbl: str) -> float:
    if len(lbl) == 2:
        return score_pair(lbl[0])
    hi, lo, t = lbl[0], lbl[1], lbl[2]
    return score_suited(hi, lo) if t == "s" else score_offsuit(hi, lo)

# ----------------------------
# Positional looseness (RFI)
# ----------------------------
def rfi_looseness(pos: str) -> float:
    return {
        "UTG": 0.05,
        "UTG1": 0.12,
        "LJ": 0.22,
        "HJ": 0.35,
        "CO": 0.55,
        "BTN": 0.80,
        "SB": 0.75,  # SB can be quite loose (but may limp)
    }.get(pos, 0.0)

def rfi_threshold(loose: float) -> float:
    return clamp01(0.80 - 0.45 * loose)

def band_mix(score: float, thr: float, width: float = 0.10) -> float:
    m = score - thr
    if m >= width:
        return 1.0
    if m <= -width:
        return 0.0
    return clamp01((m + width) / (2 * width))

# ----------------------------
# RFI with LIMP (CALL=limp in RFI spots)
# ----------------------------
def limp_tendency(pos: str, lbl: str) -> float:
    """
    Returns a 0..1 "limp preference" value used only in RFI spots.

    Cash heuristics:
      - SB is the primary limp seat (SB completion/limp strategy exists).
      - Limp prefers: suited hands, connectors/gappers, weaker offsuit that don't want to bloat pot.
      - Strong hands should mostly raise (limp rarely).
    """
    s = hand_score(lbl)

    if pos == "SB" and SB_LIMP_ENABLED:
        base = 0.0

        # suited / connected hands like to limp sometimes
        if len(lbl) == 3 and lbl[2] == "s":
            base += 0.35
            hi, lo = lbl[0], lbl[1]
            gap = abs(IDX[lo] - IDX[hi])
            if gap <= 2:
                base += 0.20

        # small pairs can mix limp
        if len(lbl) == 2 and lbl[0] in "23456789":
            base += 0.25

        # weak offsuit broadway is usually raise/fold, not limp-heavy
        if len(lbl) == 3 and lbl[2] == "o":
            base -= 0.10

        # very strong hands limp less
        base *= (1.0 - 0.9 * s)

        return clamp01(base)

    if pos == "BTN" and BTN_LIMP_ENABLED:
        # optional: tiny BTN limp strategy
        base = 0.12
        base *= (1.0 - 0.95 * s)
        return clamp01(base)

    if pos == "CO" and CO_LIMP_ENABLED:
        base = 0.05
        base *= (1.0 - 0.95 * s)
        return clamp01(base)

    return 0.0

def freqs_rfi_cash_with_limp(lbl: str, pos: str) -> Tuple[float, float, float]:
    """
    RFI spot outputs:
      RAISE / LIMP / FOLD  -> encoded as (RAISE, CALL, FOLD) for the trainer.
    """
    s = hand_score(lbl)
    loose = rfi_looseness(pos)
    thr = rfi_threshold(loose)

    # total VPIP (raise or limp) decision
    vpip = band_mix(s + 0.20 * loose, thr, width=0.11)

    if vpip <= 0:
        return (0.0, 0.0, 1.0)

    # split vpip into limp vs raise (mainly SB)
    limp_pref = limp_tendency(pos, lbl)  # 0..1
    # scale: at most ~55% of your vpip becomes limp for SB fringe hands
    limp_share = clamp01(0.55 * limp_pref)

    limp = vpip * limp_share
    raise_ = vpip - limp
    fold = 1.0 - vpip
    return (raise_, limp, fold)

# ----------------------------
# VS OPEN (RAISE=3bet, CALL=call)
# ----------------------------
def pressure_factor(hero: str, opener: str) -> float:
    dist = POS_I[hero] - POS_I[opener]
    return clamp01(0.15 + 0.12 * dist)

def freqs_vs_open(lbl: str, hero: str, opener: str) -> Tuple[float, float, float]:
    s = hand_score(lbl)
    pf = pressure_factor(hero, opener)

    opener_tight = 1.0 - rfi_looseness(opener)
    base_thr = 0.72 - 0.18 * pf + 0.10 * opener_tight
    cont = band_mix(s + 0.10 * pf, base_thr, width=0.12)

    three_thr = 0.80 - 0.20 * pf
    three_share = band_mix(s, three_thr, width=0.15)

    three = cont * three_share
    call = cont * (1.0 - three_share)
    fold = 1.0 - cont
    return (three, call, fold)

# ----------------------------
# VS 3BET (RAISE=4bet, CALL=call)
# ----------------------------
def freqs_vs_3bet(lbl: str, opener: str, threebettor: str) -> Tuple[float, float, float]:
    s = hand_score(lbl)
    dist = POS_I[threebettor] - POS_I[opener]
    aggressor_pressure = clamp01(0.20 + 0.10 * dist)

    cont_thr = 0.86 + 0.06 * aggressor_pressure
    cont = band_mix(s, cont_thr, width=0.10)

    four_thr = 0.95
    four_share = band_mix(s, four_thr, width=0.06)

    four = cont * four_share
    call = cont * (1.0 - four_share)
    fold = 1.0 - cont
    return (four, call, fold)

# ----------------------------
# Writers
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
    out_dir = Path("charts_matrix_8max_all_cash_limp")
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0

    # 1) RFI spots (exclude BB)
    for pos in POSITIONS_8MAX:
        if pos == "BB":
            continue
        spot = f"RFI_{pos}"
        p = write_matrix(
            spot,
            out_dir,
            cell_func=lambda lbl, pos=pos: freqs_rfi_cash_with_limp(lbl, pos)
        )
        print(f"Wrote {p.name}")
        written += 1

    # 2) VS OPEN spots: all hero positions behind opener
    for opener in POSITIONS_8MAX:
        if opener == "BB":
            continue
        for hero in POSITIONS_8MAX:
            if POS_I[hero] <= POS_I[opener]:
                continue
            spot = f"VS_{opener}_OPEN_{hero}"
            p = write_matrix(
                spot,
                out_dir,
                cell_func=lambda lbl, hero=hero, opener=opener: freqs_vs_open(lbl, hero, opener)
            )
            print(f"Wrote {p.name}")
            written += 1

    # 3) VS 3BET spots: opener vs any position behind that 3bets
    for opener in POSITIONS_8MAX:
        if opener == "BB":
            continue
        for threebettor in POSITIONS_8MAX:
            if POS_I[threebettor] <= POS_I[opener]:
                continue
            spot = f"RFI_{opener}_VS_3BET_{threebettor}"
            p = write_matrix(
                spot,
                out_dir,
                cell_func=lambda lbl, opener=opener, threebettor=threebettor: freqs_vs_3bet(lbl, opener, threebettor)
            )
            print(f"Wrote {p.name}")
            written += 1

    # README (important: how to interpret CALL in RFI spots)
    readme = out_dir / "README.txt"
    readme.write_text(
        "charts_matrix_8max_all_cash_limp\n"
        "Auto-generated baseline preflop matrices for 8-max cash, including limp frequencies.\n\n"
        "Spot naming:\n"
        "  RFI_<POS>                     -> open-raise first in (RAISE/LIMP/FOLD)\n"
        "  VS_<OPENER>_OPEN_<HERO>       -> HERO faces OPENER open (RAISE=3bet, CALL=call, FOLD=fold)\n"
        "  RFI_<OPENER>_VS_3BET_<POS>    -> OPENER faces 3bet (RAISE=4bet, CALL=call, FOLD=fold)\n\n"
        "IMPORTANT FOR YOUR TRAINER:\n"
        "  In RFI spots, the generator encodes LIMP as CALL.\n"
        "  So: RAISE=open-raise, CALL=limp, FOLD=fold.\n\n"
        "Cell format:\n"
        "  AKs:R70/C30/F0\n\n"
        "Note: This is NOT solver-GTO. It's a heuristic baseline for training.\n",
        encoding="utf-8"
    )

    print(f"\nDone. Wrote {written} matrix files into: {out_dir.resolve()}")
    print("Use them by running your trainer inside this folder, or copy *.csv next to gto_trainer_8max.py.")

if __name__ == "__main__":
    main()