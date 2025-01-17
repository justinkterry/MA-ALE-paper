import torch
from all.core import State, StateArray
from ._body import Body


class FrameStack(Body):
    def __init__(self, agent, size=4, lazy=False):
        super().__init__(agent)
        self._frames = []
        self._size = size
        self._lazy = lazy
        self._to_cache = ToCache()

    def process_state(self, state):
        if not self._frames:
            self._frames = [state.observation] * self._size
        else:
            self._frames = self._frames[1:] + [state.observation]
        if self._lazy:
            return LazyState.from_state(state, self._frames, self._to_cache)
        if isinstance(state, StateArray):
            return state.update('observation', torch.cat(self._frames, dim=1))
        return state.update('observation', torch.cat(self._frames, dim=0))


class ToCache:
    def __init__(self, from_device=None, to_device=None, max_size=16):
        self.from_device = from_device
        self.to_device = to_device
        self.max_size = max_size
        self.cache_data = []

    def convert(self, value, device):
        if self.from_device is None:
            self.from_device = value.device
        if self.to_device is None:
            self.to_device = device
        if self.from_device != value.device or self.to_device != device:
            raise ValueError("bad devices to convert lazystate, must be internally consistent")

        cached = None
        for el in self.cache_data:
            if el[0] is value:
                cached = el[1]
                break
        if cached is not None:
            new_v = cached
        else:
            new_v = value.to(device)
            self.cache_data.append((value, new_v))
            if len(self.cache_data) > self.max_size:
                self.cache_data.pop(0)
        return new_v


class LazyState(State):
    @classmethod
    def from_state(cls, state, frames, to_cache):
        state = LazyState(state, device=frames[0].device)
        state.to_cache = to_cache
        state['observation'] = frames
        return state

    def __getitem__(self, key):
        if key == 'observation':
            v = dict.__getitem__(self, key)
            if torch.is_tensor(v):
                return v
            return torch.cat(dict.__getitem__(self, key), dim=0)
        return super().__getitem__(key)

    def update(self, key, value):
        x = {}
        for k in self.keys():
            if not k == key:
                x[k] = super().__getitem__(k)
        x[key] = value
        state = LazyState(x, device=self.device)
        state.to_cache = self.to_cache
        return state

    def to(self, device):
        if device == self.device:
            return self
        x = {}
        for key, value in self.items():
            if key == 'observation':
                x[key] = [self.to_cache.convert(v, device) for v in value]
                # x[key] = [v.to(device) for v in value]#torch.cat(value,axis=0).to(device)
            elif torch.is_tensor(value):
                x[key] = value.to(device)
            else:
                x[key] = value
        state = LazyState.from_state(x, x['observation'], self.to_cache)
        return state
