"""Blood-group rules shared by the generator and the engines.

Simplified red-cell ABO/Rh compatibility for a demonstration prototype.
Not clinical guidance.
"""

from app.models.enums import BloodGroup

_G = BloodGroup

# Recipient blood group → donor groups the demo treats as compatible.
COMPATIBLE_DONORS: dict[BloodGroup, tuple[BloodGroup, ...]] = {
    _G.O_NEG: (_G.O_NEG,),
    _G.O_POS: (_G.O_POS, _G.O_NEG),
    _G.A_NEG: (_G.A_NEG, _G.O_NEG),
    _G.A_POS: (_G.A_POS, _G.A_NEG, _G.O_POS, _G.O_NEG),
    _G.B_NEG: (_G.B_NEG, _G.O_NEG),
    _G.B_POS: (_G.B_POS, _G.B_NEG, _G.O_POS, _G.O_NEG),
    _G.AB_NEG: (_G.AB_NEG, _G.A_NEG, _G.B_NEG, _G.O_NEG),
    _G.AB_POS: tuple(BloodGroup),
}
