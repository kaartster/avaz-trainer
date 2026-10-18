import numpy as np
import pytest

from avaz.keys import scale_note_name
from avaz.notes import lane_edges, note_blocks


def test_lane_edges_reach_halfway_to_neighbours():
    lanes = lane_edges([0, 150, 300])
    assert lanes == [(0.0, -75.0, 75.0), (150.0, 75.0, 225.0), (300.0, 225.0, 375.0)]
    assert lane_edges([]) == []
    assert lane_edges([500]) == [(500.0, 450.0, 550.0)]


def test_note_blocks_follow_the_nearest_note():
    hop = 0.01
    t = np.arange(0, 1.0, hop)
    c = np.where(t < 0.5, 10.0, 290.0)          # a slightly sharp tonic, then a flat third
    b = note_blocks(t, c, [0, 150, 300])
    assert list(b["center"]) == [0.0, 300.0]
    assert b["t0"][0] == pytest.approx(0.0) and b["t1"][0] == pytest.approx(0.5)
    assert b["t1"][1] == pytest.approx(1.0)
    assert list(b["dev"]) == [pytest.approx(10.0), pytest.approx(-10.0)]


def test_note_blocks_bridge_short_gaps_and_drop_short_blips():
    hop = 0.01
    t = np.arange(0, 1.0, hop)
    c = np.full(t.size, 0.0)
    c[30:32] = np.nan                            # 20 ms dropout: same block
    c[60:63] = 150.0                             # 30 ms touch of the next note: dropped
    c[80:] = np.nan                              # long silence: block ends
    b = note_blocks(t, c, [0, 150, 300])
    assert list(b["center"]) == [0.0, 0.0]       # split only by the blip
    assert b["t0"][0] == 0.0 and b["t1"][0] == pytest.approx(0.60)
    assert b["t0"][1] == pytest.approx(0.63) and b["t1"][1] == pytest.approx(0.80)
    empty = note_blocks(t, np.full(t.size, np.nan), [0, 150])
    assert empty["t0"].size == 0


def test_note_blocks_do_not_flicker_between_two_lanes():
    hop = 0.01
    t = np.arange(0, 2.0, hop)
    c = -440 + 18 * np.sin(2 * np.pi * 5.5 * t)   # vibrato around the La / Si bemol midpoint
    b = note_blocks(t, c, [-500, -400, -200])
    assert list(b["center"]) == [-400.0]
    b = note_blocks(t, c, [-500, -400, -200], stickiness=0)
    assert len(b["center"]) > 3                  # without it: many short blocks


def test_scale_note_name_with_koron_and_sori():
    mi = 164.81
    assert scale_note_name(mi, 0) == "Mi"
    assert scale_note_name(mi, 150) == "Fa sori"        # Shur on Mi: second degree
    assert scale_note_name(mi, 300) == "Sol"
    assert scale_note_name(mi, 1200) == "Mi"
    la = 220.0
    assert scale_note_name(la, 150) == "Si koron"       # Shur on La
    assert scale_note_name(la, -200) == "Sol"
    assert scale_note_name(185.0, 0) == "Fa diez"
    assert scale_note_name(167.0, 0) == "Mi"            # the teacher's Mi, 23 cents sharp


def test_break_jumps_gaps_one_frame_octave_slips():
    from avaz.notes import break_jumps
    t = np.arange(6) * 0.006
    c = [0.0, 10.0, 1210.0, 20.0, 30.0, 400.0]     # an octave slip and a fast but real move
    _, out = break_jumps(t, c)
    assert np.isnan(out[2]) and np.isnan(out[3])
    assert out[5] == 400.0 and out[0] == 0.0
    assert c[2] == 1210.0                          # the input is not modified
