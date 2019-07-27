"""This module defines the learning2write gym environment."""

import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Tuple

import gym
import numpy as np
import pyglet
from gym import spaces
from gym.envs.classic_control import rendering
from pyglet.window import key

from learning2write.patterns import PatternSet, Patterns3x3

MOVE_UP = 0
MOVE_DOWN = 1
MOVE_LEFT = 2
MOVE_RIGHT = 3
FILL_SQUARE = 4
QUIT = 5


class WritingEnvironment(gym.Env):
    """A custom gym environment for teaching RL agents how to write."""
    metadata = {'render.modes': ['human', 'text']}

    N_DISCRETE_ACTIONS = 6

    def __init__(self, pattern_set: PatternSet = None, cell_size=80):
        """Create a writing environment.

        :param pattern_set: The set of patterns to use.
        :param cell_size: The size of the squares representing a 'pixel' in the pattern.
        """
        super(WritingEnvironment, self).__init__()

        # Environment State
        self.pattern_set = pattern_set if pattern_set else Patterns3x3()
        self.rows = self.pattern_set.HEIGHT
        self.cols = self.pattern_set.WIDTH
        self.pattern_shape = (self.rows, self.cols)
        self.pattern: np.ndarray = np.zeros(self.pattern_shape)
        self.reference_pattern: np.ndarray = np.zeros(self.pattern_shape)
        # Agent State
        self.agent_position: np.ndarray = np.zeros(2, dtype=int)
        # GUI
        self.viewer: Optional[rendering.Viewer] = None
        self.cell_size = cell_size
        self.window_height = (self.rows + 2) * self.cell_size
        self.window_width = (2 * self.cols + 4) * self.cell_size
        # Spaces
        self.action_space = spaces.Discrete(WritingEnvironment.N_DISCRETE_ACTIONS)
        self.observation_space = spaces.Box(low=0, high=1, shape=(self.rows, self.cols, 3), dtype=np.uint8)

    @property
    def state(self) -> np.ndarray:
        """Get the current state of the environment.

        :return: The state as a tensor.
        """
        pos = np.zeros(self.pattern_shape)
        row, col = self.agent_position
        pos[row, col] = 1

        return np.stack((self.pattern, self.reference_pattern, pos))

    @property
    def should_quit(self) -> bool:
        """Check whether the window has been closed or the user pressed the key `Q` or `ESCAPE`.

        :return: Whether or not the parent program should quit.
        """
        return self.viewer and \
               (not self.viewer.isopen or self.keys.key_was_pressed(key.ESCAPE) or self.keys.key_was_pressed(key.Q))

    def seed(self, seed=None):
        self.pattern_set.seed(seed)
        random.seed(seed)

        return [seed]

    def reset(self):
        self.pattern = np.zeros(self.pattern_shape)
        self.agent_position = np.zeros(2, dtype=int)
        self.reference_pattern = self.pattern_set.sample()
        self.reference_pattern = np.rot90(self.reference_pattern, k=random.randint(0, 3))

        return self.state

    def step(self, action: int):
        # TODO: Refactor this to somewhere more accessible
        move_reward = -1
        correct_square_reward = 3
        incorrect_square_reward = -2
        bad_end = -100
        good_end = 100
        out_of_bounds = -1000

        done = False
        info = dict()

        if action == FILL_SQUARE:
            row, col = self.agent_position

            # Agent shouldn't try to fill the same cell twice.
            if self.pattern[row, col]:
                reward = incorrect_square_reward
            else:
                self.pattern[row, col] = 1

                # Agent should only fill in cells that are also filled in the reference pattern
                if self.reference_pattern[row, col] == 1:
                    reward = correct_square_reward
                else:
                    reward = incorrect_square_reward
        elif action == QUIT:
            # Agent should only quit when the pattern has been copied exactly.
            reward = good_end if np.array_equal(self.pattern, self.reference_pattern) else bad_end
            done = True
        elif 0 <= action < WritingEnvironment.N_DISCRETE_ACTIONS:
            # Agent should only move within the defined grid world.
            if self._move(action):
                reward = move_reward
            else:
                reward = out_of_bounds
                done = True
        else:
            raise ValueError('Unrecognised action: %s' % str(action))

        return self.state, reward, done, info

    def render(self, mode='human', close=False):
        if mode == 'text':
            self._render_text()
        elif mode in {'human', 'rgb_array'}:
            return self._render(mode)
        else:
            raise NotImplementedError

    def wait(self, duration):
        """Essentially perform a no-op while still processing GUI events.

        :returns: False is window was closed during wait, True otherwise.
        """
        duration = timedelta(seconds=duration)
        start = datetime.now()

        self.viewer.window.dispatch_events()
        delta = timedelta()

        while delta < duration:
            if self.should_quit:
                return False

            self.viewer.window.dispatch_events()
            delta = datetime.now() - start

        return True

    def close(self):
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None

    def _move(self, direction) -> bool:
        """Move the agent and update its position.

        :param direction: The direction to move the agent.
        :return: True if the move resulted in a valid position and the agent's position was updated, False otherwise.
        """
        row, col = self.agent_position

        if direction == MOVE_UP:
            row -= 1  # Visually, 2d arrays start at the top-left corner and rows increase in number as they go down.
        elif direction == MOVE_DOWN:
            row += 1
        elif direction == MOVE_LEFT:
            col -= 1
        elif direction == MOVE_RIGHT:
            col += 1
        else:
            raise ValueError('Unrecognised direction \'%d\'.' % direction)

        new_pos = (row, col)

        if self._is_position_valid(new_pos):
            self.agent_position = new_pos
            return True
        else:
            return False

    def _is_position_valid(self, point):
        """Check if a proposed agent position is valid or not.

        :param point: The point to check.
        :return: True if the point is within the valid bounds, False otherwise.
        """
        row, col = point

        return 0 <= row < self.rows and 0 <= col < self.cols

    def _render_text(self):
        """Render a text representation of the environment."""
        print('―' * 2 * (self.cols + 2))

        for row in range(self.rows):
            pattern_string = '|'
            reference_pattern_string = '|'

            for col in range(self.cols):
                cell_val = self.pattern[row, col]

                if cell_val == 0:
                    mark = ' '
                elif cell_val == 1 == self.reference_pattern[row, col]:
                    mark = 'o'
                else:
                    mark = 'x'

                pattern_string += '%s' % mark
                reference_pattern_string += 'o' if self.reference_pattern[row, col] else ' '

            pattern_string += '|'
            reference_pattern_string += '|'
            print(reference_pattern_string + pattern_string)

        print('―' * 2 * (self.cols + 2))

    def _render(self, mode='human'):
        """Render the environment to a window.

        :return: If mode is 'human', returns True if the display window is still open, otherwise false.
                 If mode is 'rgb_array', returns a ndarray of the raw pixels.
        """
        if self.viewer is None:
            self.viewer = rendering.Viewer(self.window_width, self.window_height)

            pyglet.gl.glClearColor(1, 1, 1, 1)
            self.keys = KeyStateHandler()
            self.viewer.window.push_handlers(self.keys)

        self._draw_state()

        return self.viewer.render(return_rgb_array=mode == 'rgb_array')

    def _draw_state(self):
        """Draw the current state (the reference pattern, the current pattern, and the agent's position)."""
        self._draw_pattern(self.reference_pattern, (self.cell_size, self.window_height - self.cell_size))
        self._draw_pattern(self.pattern, (self.window_width // 2 + self.cell_size, self.window_height - self.cell_size),
                           draw_position_marker=True)

    def _draw_pattern(self, pattern: np.ndarray, origin: Tuple[int, int], draw_position_marker: bool = False):
        """Draw a pattern.

        :param pattern: The pattern to draw.
        :param origin: The pixel coordinates of the top left corner of where to draw the pattern.
        :param draw_position_marker: Whether or not to draw the agent's position marker onto the pattern.
        """
        x, y = origin

        for row in range(self.cols):
            for col in range(self.rows):
                self._draw_cell((x + col * self.cell_size, y - row * self.cell_size), filled=pattern[row, col] > 0)

        if draw_position_marker:
            row, col = self.agent_position
            self._draw_position_marker((x + col * self.cell_size, y - (row + 1) * self.cell_size))

    def _draw_cell(self, origin, filled=True):
        """Draw a 'cell', or something close to a pixel, of a pattern.

        :param origin: The pixel coordinates of the top left corner of the cell to draw.
        :param filled: Whether or not to colour in the shape.
        """
        x, y = origin
        bl = [x, y]
        br = [x + self.cell_size, y]
        tl = [x, y - self.cell_size]
        tr = [x + self.cell_size, y - self.cell_size]

        self.viewer.draw_polygon([bl, tl, tr, br], filled, color=(0, 0, 0))

    def _draw_position_marker(self, origin, filled=True, resolution=16):
        """Draw a 'cell', or something close to a pixel, of a pattern.

        :param origin: The pixel coordinates of the top left corner of the cell to draw.
        :param filled: Whether or not to colour in the shape.
        :param resolution: How many points to use for drawing the circle. Most points means a smoother circle.
        """
        radius = self.cell_size / 4
        offset = self.cell_size // 2

        geom = self.viewer.draw_circle(radius, resolution, filled, color=(255, 0, 0))

        for i, point in enumerate(geom.v):
            geom.v[i] = (point[0] + origin[0] + offset, point[1] + origin[1] + offset)


class KeyStateHandler:
    """Simple handler that tracks the state of keys on the keyboard. If a
    key is pressed then this handler holds a True value for it.

    For example::

        >>> win = pyglet.window.Window
        >>> keyboard = KeyStateHandler()
        >>> win.push_handlers(keyboard)

        # Hold down the "up" arrow...

        >>> keyboard[key.UP]
        True
        >>> keyboard.key_was_pressed(key.UP)
        True
        >>> keyboard.key_was_released(key.UP)
        False
        >>> keyboard.key_was_held(key.UP)
        True
        >>> keyboard[key.DOWN]
        False

    """

    def __init__(self):
        self.curr_state = defaultdict(lambda: False)
        self.prev_state = defaultdict(lambda: False)

    def on_key_press(self, symbol, modifiers):
        self.prev_state[symbol] = self.curr_state[symbol]
        self.curr_state[symbol] = True

    def on_key_release(self, symbol, modifiers):
        self.prev_state[symbol] = self.curr_state[symbol]
        self.curr_state[symbol] = False

    def key_was_pressed(self, symbol):
        return not self.prev_state[symbol] and self.curr_state[symbol]

    def key_was_released(self, symbol):
        return self.prev_state[symbol] and not self.curr_state[symbol]

    def key_was_held(self, symbol):
        return self.prev_state[symbol] and self.curr_state[symbol]

    def __getitem__(self, key):
        return self.curr_state[key]