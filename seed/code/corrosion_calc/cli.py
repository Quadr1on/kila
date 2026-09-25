import sys

from .rates import corrosion_rate, next_inspection_years, remaining_life

if __name__ == "__main__":
    t_prev, t_act, t_min, years = map(float, sys.argv[1:5])
    cr = corrosion_rate(t_prev, t_act, years)
    rl = remaining_life(t_act, t_min, cr)
    print(f"CR={cr:.3f} mm/yr RL={rl} yr next={next_inspection_years(rl):.1f} yr")
