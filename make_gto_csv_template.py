import csv
from pathlib import Path

# Chart-style order (top/left starts with A then down to 2)
RANKS = "AKQJT98765432"

# 8-max positions
POSITIONS_8MAX = ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"]

def hand_label(r_row: str, r_col: str) -> str:
    """
    13x13 chart convention:
      - Diagonal: pairs (AA)
      - Above diagonal: suited (AKs)
      - Below diagonal: offsuit (AKo)
    """
    if r_row == r_col:
        return r_row + r_col

    row_i = RANKS.index(r_row)
    col_i = RANKS.index(r_col)

    if row_i < col_i:
        # above diagonal
        return f"{r_row}{r_col}s"
    else:
        # below diagonal (note order is high-low)
        return f"{r_col}{r_row}o"

def write_matrix_csv(spot: str, out_dir: Path, placeholder: str = "R__/C__/F__") -> Path:
    out_path = out_dir / f"{spot}_matrix.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)

        # header
        w.writerow([spot] + list(RANKS))

        # grid
        for r_row in RANKS:
            row = [r_row]
            for r_col in RANKS:
                lbl = hand_label(r_row, r_col)
                # readable cell: "AKs:R__/C__/F__"
                row.append(f"{lbl}:{placeholder}")
            w.writerow(row)

    return out_path

def main():
    out_dir = Path("charts_matrix_8max")
    out_dir.mkdir(parents=True, exist_ok=True)

    # RFI spots for 8-max (exclude BB)
    rfi_positions = [p for p in POSITIONS_8MAX if p != "BB"]
    spots = [f"RFI_{p}" for p in rfi_positions]

    for spot in spots:
        p = write_matrix_csv(spot, out_dir=out_dir, placeholder="R__/C__/F__")
        print(f"Wrote {p}")

    print("\nDone. Fill each cell with frequencies from your GTO source.")
    print("Example cell format: AKs:R70/C30/F0  (or keep the R__/C__/F__ placeholders)")

if __name__ == "__main__":
    main()