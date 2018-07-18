from collections import UserDict, UserList
from typing import List
from abc import ABC, abstractmethod

class BasicCWLNode(ABC):
    _path = NotImplemented

    @property
    def path(self):
        return self._path


class BasicCWLNodeDict(UserDict, BasicCWLNode):
    def __init__(self, json, path: List) -> None:
        self._json = json
        self._path = path

    @property
    def data(self):
        new_data = {}
        for key, value in self._json.items():
            if isinstance(value, dict):
                new_data[key] = BasicCWLNodeDict(value, self._path + [key])
            elif isinstance(value, list):
                new_data[key] = BasicCWLNodeList(value, self._path + [key])
            else:
                new_data[key] = value

        return new_data

class BasicCWLNodeList(UserList, BasicCWLNode):
    def __init__(self, json, path: List) -> None:
        self._json = json
        self._path = path

    @property
    def data(self):
        new_data = []
        for x, i in enumerate(self._json):
            if isinstance(x, dict):
                new_data.append(BasicCWLNodeDict(x, self._path + [i]))
            elif isinstance(x, list):
                new_data.append(BasicCWLNodeList(x, self._path + [i]))
            else:
                new_data.append(x)

        return new_data

class CWLFile(BasicCWLNodeDict):
    def __init__(self, json):
        self._base_node = BasicCWLNodeDict(json, [])

    @property
    def data(self):
        return self._base_node.data