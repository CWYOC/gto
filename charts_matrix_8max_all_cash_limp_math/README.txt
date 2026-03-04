Math-leaning baseline charts (NOT solver-GTO)

Key ideas used:
- Chen-style hand strength -> rough equity proxy
- Calls use pot-odds + rake penalty
- 3bet and 4bet are value + blocker bluffs, with target frequencies by position
- RFI spots include SB limps (CALL in RFI = LIMP)

Spot interpretation for your trainer:
  RFI_*               -> RAISE / LIMP / FOLD  (LIMP stored as CALL)
  VS_*_OPEN_*         -> 3BET / CALL / FOLD   (3BET stored as RAISE)
  RFI_*_VS_3BET_*     -> 4BET / CALL / FOLD   (4BET stored as RAISE)
