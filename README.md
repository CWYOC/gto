# gto
This is a random gto pratice tool for free
charts_matrix_8max_all_cash_limp
Auto-generated baseline preflop matrices for 8-max cash, including limp frequencies.

Spot naming:
  RFI_<POS>                     -> open-raise first in (RAISE/LIMP/FOLD)
  VS_<OPENER>_OPEN_<HERO>       -> HERO faces OPENER open (RAISE=3bet, CALL=call, FOLD=fold)
  RFI_<OPENER>_VS_3BET_<POS>    -> OPENER faces 3bet (RAISE=4bet, CALL=call, FOLD=fold)

IMPORTANT FOR YOUR TRAINER:
  In RFI spots, the generator encodes LIMP as CALL.
  So: RAISE=open-raise, CALL=limp, FOLD=fold.

Cell format:
  AKs:R70/C30/F0

Note: This is NOT solver-GTO. It's a heuristic baseline for training.

# Generates "math-leaning" (pot-odds + rake) 8-max cash preflop charts WITH limps (SB).

Output folder:
  charts_matrix_8max_all_cash_limp_math/

Use with your updated gto.py trainer:
  python gen_all_8max_cash_limp_math.py
  python gto.py --dir charts_matrix_8max_all_cash_limp_math

Notes:
- RFI_* spots: CALL = LIMP (so actions are RAISE/LIMP/FOLD)
- VS_*_OPEN_* spots: RAISE = 3BET
- RFI_*_VS_3BET_* spots: RAISE = 4BET
- Calls use pot odds + rake penalty
- Strength uses Chen-style score -> equity proxy
- 3bet/4bet are value + blocker bluffs with position-based targets