"""Logic tests -- run anywhere (no Pi needed):  python3 test_elevator.py"""
import unittest

from elevator import Elevator, UP, DOWN, HOLD


def run_until_idle(car, limit=100):
    """Step until the cab is idle; return the list of floors where the doors opened."""
    opened = []
    for _ in range(limit):
        car.step()
        if car.doors_open and (not opened or opened[-1] != car.floor):
            opened.append(car.floor)
        if not car.stops() and not car.doors_open and car.direction == HOLD:
            return opened
    raise AssertionError("elevator never went idle")


class ElevatorTests(unittest.TestCase):
    def test_single_request_up(self):
        car = Elevator(6, 3, 3)
        car.press_floor(5)
        self.assertEqual(run_until_idle(car), [5])
        self.assertEqual(car.floor, 5)
        self.assertEqual(car.car_calls, set())

    def test_keeps_direction_then_reverses(self):
        car = Elevator(6, 3, 3)
        car.press_floor(5)
        car.step()                       # 3 -> 4, heading up
        car.press_floor(1)               # behind us
        car.press_floor(6)               # ahead of us
        self.assertEqual(run_until_idle(car), [5, 6, 1])

    def test_lobby_call_brings_cab_and_clears_both_lamps(self):
        car = Elevator(6, 3, 6)
        car.press_call(UP)
        car.press_call(DOWN)
        self.assertEqual(run_until_idle(car), [3])
        self.assertFalse(car.hall_up or car.hall_down)

    def test_floor_press_while_call_pending_is_not_lost(self):
        # Upstream bug: with both call lamps lit, a floor press was treated as a DOWN call.
        car = Elevator(6, 3, 1)
        car.press_call(UP)
        car.press_call(DOWN)
        car.press_floor(5)
        self.assertIn(5, car.car_calls)
        self.assertEqual(run_until_idle(car), [3, 5])

    def test_press_current_floor_when_idle_opens_doors(self):
        car = Elevator(6, 3, 3)
        car.press_floor(3)
        self.assertTrue(car.doors_open)
        self.assertEqual(car.car_calls, set())
        car.step()
        self.assertFalse(car.doors_open)

    def test_never_leaves_shaft(self):
        car = Elevator(6, 3, 3)
        for f in (1, 6, 2, 5):
            car.press_floor(f)
        for _ in range(60):
            car.step()
            self.assertTrue(1 <= car.floor <= 6)

    def test_out_of_range_ignored(self):
        car = Elevator(6, 3, 3)
        car.press_floor(9)
        self.assertEqual(car.stops(), set())

    def test_idle_picks_nearest(self):
        car = Elevator(6, 3, 3)
        car.press_floor(1)
        car.press_floor(6)
        car.step()
        self.assertEqual(car.direction, DOWN)   # 1 is 2 away, 6 is 3 away


if __name__ == "__main__":
    unittest.main(verbosity=2)
