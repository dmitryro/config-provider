import yaml
import os.path


class LoaderMeta(type):
    """ Meta class for loader """
    def __new__(metacls, __name__, __bases__, __dict__):
        """Add include constructer to class."""

        # register the include constructor on the class
        cls = super().__new__(metacls, __name__, __bases__, __dict__)
        cls.add_constructor('!include', cls.include)
        cls.add_constructor('!import', cls.include)

        return cls


class Loader(yaml.Loader, metaclass=LoaderMeta):
    """ Yaml Loader """
    def __init__(self, stream):

        try:
            self._root = os.path.split(stream.name)[0]
        except AttributeError:
            self._root = os.path.curdir

        super(Loader, self).__init__(stream)
        Loader.add_constructor('!include', Loader.include)
        Loader.add_constructor('!import',  Loader.include)

    def include(self, node):
        if isinstance(node, yaml.ScalarNode):
            return self.extractFile(self.construct_scalar(node))
        elif isinstance(node, yaml.SequenceNode):
            result = []
            for filename in self.construct_sequence(node):
                result += self.extractFile(filename)
            return result
 
        elif isinstance(node, yaml.MappingNode):
            result = {}
            for k, v in self.construct_mapping(node).iteritems():
                result[k] = self.extractFile(v)
            return result
 
        else:
            print("Error:: unrecognised node type in !include statement")
            raise yaml.constructor.ConstructorError
 
    def extractFile(self, filename):
        filepath = "."+os.path.join(self._root, filename)
        with open(filepath, 'r') as f:
            return yaml.load(f, Loader)
