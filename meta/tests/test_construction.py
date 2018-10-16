import unittest

from meta.construction import Singleton


class SingletonTest(unittest.TestCase):

    maxDiff = None

    def test_instancing_a_singleton_class(self):
        # Given...
        class TestSingleton(metaclass=Singleton):
            pass
        # When...
        singleton_a = TestSingleton()
        singleton_b = TestSingleton()
        # Then...
        self.assertIs(singleton_a, singleton_b)

    def test_instancing_a_singleton_subclass(self):
        # Given...
        class TestSingletonParent(metaclass=Singleton):
            pass

        class TestSingletonChild(TestSingletonParent):
            pass
        # When...
        singleton_a = TestSingletonChild()
        singleton_b = TestSingletonChild()
        # Then...
        self.assertIs(singleton_a, singleton_b)
