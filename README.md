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
