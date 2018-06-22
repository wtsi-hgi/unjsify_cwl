from collections import UserDict, UserList

class BasicCWLNode:
    def hello(self):
        print("hi")


class BasicCWLNodeDict(UserDict, BasicCWLNode):
    def __init__(self, json):
        self._json = json

    @property
    def data(self):
        new_data = {}
        for key, value in self._json.items():
            if isinstance(value, dict):
                new_data[key] = BasicCWLNodeDict(value)
            elif isinstance(value, list):
                new_data[key] = BasicCWLNodeDict(value)
            else:
                new_data[key] = value

        return new_data

class BasicCWLNodeList(UserList, BasicCWLNode):
    def __init__(self, json):
        self._json = json

    @property
    def data(self):
        new_data = []
        for x in self._json:
            if isinstance(x, dict):
                new_data.append(BasicCWLNodeDict(x))
            elif isinstance(x, list):
                new_data.append(BasicCWLNodeDict(x))
            else:
                new_data.append(x)

        return new_data