# gto
This is a random gto pratice tool for free

# This is just pure math and for fun only, ME and My Team will not afford any lost in gambling.

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

# Notes:
- RFI_* spots: CALL = LIMP (so actions are RAISE/LIMP/FOLD)
- VS_*_OPEN_* spots: RAISE = 3BET
- RFI_*_VS_3BET_* spots: RAISE = 4BET
- Calls use pot odds + rake penalty
- Strength uses Chen-style score -> equity proxy
- 3bet/4bet are value + blocker bluffs with position-based targets

# This is NOT solver-GTO. It's a heuristic baseline for training.

Also I have build a website providing the same function too,
which you can see above. For those who don't know how to use github,
here is the link for you.

https://cwyoc.github.io/gto/