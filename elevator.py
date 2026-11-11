"""
Pure elevator logic -- no GPIO, no LCD. Easy to read and to test on any PC.

The cab works like a real "collective" elevator:
  * Keep going in the current direction while there is any stop ahead.
  * Then reverse if there are stops behind, otherwise go idle (HOLD).
  * When idle, head for the nearest stop.
  * Stopping at a floor clears that floor's request (its LED goes off) and
    the cab waits one dwell period with the doors open.
  * The exterior UP/DOWN call buttons live on the lobby floor: pressing
    either one makes the lobby a stop; both call lamps clear when the cab
    arrives there.

All public methods are thread-safe (button presses arrive from a polling
thread while the main loop calls step()).
"""
import threading

UP, DOWN, HOLD = "UP", "DOWN", "HOLD"


class Elevator:
    def __init__(self, total_floors, lobby_floor, start_floor):
        if not 1 <= lobby_floor <= total_floors:
            raise ValueError("LOBBY_FLOOR must be between 1 and TOTAL_FLOORS")
        if not 1 <= start_floor <= total_floors:
            raise ValueError("START_FLOOR must be between 1 and TOTAL_FLOORS")
        self.total_floors = total_floors
        self.lobby = lobby_floor
        self.floor = start_floor
        self.direction = HOLD
        self.doors_open = False
        self.car_calls = set()      # floors requested from inside the cab
        self.hall_up = False        # exterior UP call (lobby)
        self.hall_down = False      # exterior DOWN call (lobby)
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- input
    def press_floor(self, floor):
        """Inside-cab floor button. Returns a short description for the log."""
        with self._lock:
            if not 1 <= floor <= self.total_floors:
                return f"ignored floor {floor} (out of range)"
            if floor == self.floor and self.direction == HOLD:
                self.doors_open = True
                return f"floor {floor} pressed - already here, doors open"
            if floor in self.car_calls:
                return f"floor {floor} pressed - already requested"
            self.car_calls.add(floor)
            return f"floor {floor} requested"

    def press_call(self, direction):
        """Exterior call button on the lobby floor (UP or DOWN)."""
        with self._lock:
            if self.floor == self.lobby and self.direction == HOLD:
                self.doors_open = True
                return f"call {direction} pressed - cab already at lobby, doors open"
            if direction == UP:
                self.hall_up = True
            else:
                self.hall_down = True
            return f"call {direction} registered at lobby (floor {self.lobby})"

    # ---------------------------------------------------------------- state
    def stops(self):
        with self._lock:
            s = set(self.car_calls)
            if self.hall_up or self.hall_down:
                s.add(self.lobby)
            return s

    def snapshot(self):
        """Copy of everything the LEDs/display need."""
        with self._lock:
            return {
                "floor": self.floor,
                "direction": self.direction,
                "doors_open": self.doors_open,
                "car_calls": sorted(self.car_calls),
                "hall_up": self.hall_up,
                "hall_down": self.hall_down,
            }

    # ---------------------------------------------------------------- motion
    def _arrive(self):
        """Serve the current floor if it is a stop."""
        if self.floor in self.stops():
            self.car_calls.discard(self.floor)
            if self.floor == self.lobby:
                self.hall_up = self.hall_down = False
            self.doors_open = True
            return True
        return False

    def step(self):
        """Advance one tick. Returns a short event string for the log, or None."""
        with self._lock:
            # Doors were open last tick: close them, don't move this tick.
            if self.doors_open:
                self.doors_open = False
                if not self.stops():
                    self.direction = HOLD
                return f"doors closing at floor {self.floor}"

            # Someone requested the floor we're sitting at.
            if self._arrive():
                return f"stopped at floor {self.floor}"

            stops = self.stops()
            if not stops:
                if self.direction != HOLD:
                    self.direction = HOLD
                    return f"idle at floor {self.floor}"
                return None

            above = any(f > self.floor for f in stops)
            below = any(f < self.floor for f in stops)
            if self.direction == UP:
                new_dir = UP if above else DOWN
            elif self.direction == DOWN:
                new_dir = DOWN if below else UP
            else:
                nearest = min(stops, key=lambda f: (abs(f - self.floor), -f))
                new_dir = UP if nearest > self.floor else DOWN

            self.direction = new_dir
            self.floor += 1 if new_dir == UP else -1
            if self._arrive():
                return f"moved {new_dir.lower()} to floor {self.floor} - stopping"
            return f"moved {new_dir.lower()} to floor {self.floor}"
