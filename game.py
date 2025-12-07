
import random
import threading
from copy import deepcopy

# Simple NxN puzzle: a Latin-square-like puzzle for demo.
# We create a complete nxn board with numbers 1..n in each row/col, then remove k cells.

class GameState:
    def __init__(self, n=3, blanks=3):
        self.n = n
        self.board = []  # 2D list, 0 means blank
        self.locked = {}  # (r,c) -> player name locking it (if needed)
        self.scores = {}  # player -> score
        self.round = 1
        self.version = 0
        self._generate_complete_board()
        self._remove_blanks(blanks)
        self._lock = threading.Lock()

    def _generate_complete_board(self):
        n = self.n
        # generate a simple Latin square by shifting
        base = list(range(1, n+1))
        self.board = [base[i:] + base[:i] for i in range(n)]

    def _remove_blanks(self, k):
        n = self.n
        cells = [(r,c) for r in range(n) for c in range(n)]
        random.shuffle(cells)
        for i in range(min(k, len(cells))):
            r,c = cells[i]
            self.board[r][c] = 0

    def as_dict(self):
        with self._lock:
            return {
                'n': self.n,
                'board': deepcopy(self.board),
                'scores': dict(self.scores),
                'round': self.round,
                'version': self.version
            }

    def is_correct_move(self, r, c, val):
        # correct if val equals the value in the underlying Latin square
        # But since blanks are actually set to 0 in board, recreate expected board
        expected = list(range(1, self.n+1))
        expected_row = expected[r:] + expected[:r]
        return expected_row[c] == val

    def apply_move(self, player, r, c, val):
        with self._lock:
            if r < 0 or c < 0 or r >= self.n or c >= self.n:
                return False, "out_of_bounds"
            if self.board[r][c] != 0:
                return False, "cell_not_empty"
            if not self.is_correct_move(r,c,val):
                # incorrect
                self.scores.setdefault(player, 0)
                self.scores[player] -= 1
                self.version += 1
                return False, "incorrect"
            # correct
            self.board[r][c] = val
            self.scores.setdefault(player, 0)
            self.scores[player] += 5
            self.version += 1
            return True, "ok"

    def set_state(self, state_dict):
        with self._lock:
            self.n = state_dict['n']
            self.board = state_dict['board']
            self.scores = state_dict['scores']
            self.round = state_dict.get('round', self.round)
            self.version = state_dict.get('version', self.version)

