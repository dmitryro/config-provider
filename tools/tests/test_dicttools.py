import unittest

from tools.dicttools import dictiter, dictpath, dictwalk


class DictToolsTest(unittest.TestCase):

    maxDiff = None

    def test_dictiter(self):
        # Given...
        dict1 = {"yeah": 2}
        dict2 = ["nah", 5, 27.72]
        # When...
        di = dictiter(dict1)
        li = dictiter(dict2)
        # Then...
        self.assertEqual(("yeah", 2), next(di))
        self.assertEqual((0, "nah"), next(li))
        self.assertEqual((1, 5), next(li))
        self.assertEqual((2, 27.72), next(li))

    def test_dictwalk(self):
        # Given...
        d = {"yeah": 2,
             "nah": "Some long phrase, for test data that is.",
             "wee": {"key": ["Yet another phrase we're going to change.",
                             4,
                             "This one we won't"]}}

        # When...
        def specify_type(k, v, path):
            if isinstance(v, str):
                return v.replace("phrase", "shovel")

            return v

        dictwalk(d, specify_type)
        # Then...
        self.assertEqual({"yeah": 2,
                          "nah": "Some long shovel, for test data that is.",
                          "wee": {"key": ["Yet another shovel we're going to change.",
                                          4,
                                          "This one we won't"]}},
                         d)

    def test_dictpath(self):
        # Given...
        d = {"yeah": 2,
             "nah": "Some long phrase, for test data that is.",
             "wee": {"key": ["Yet another phrase we're going to change.",
                             4,
                             "This one we won't"]}}
        # When...
        v = dictpath(d, ["wee", "key"])
        # Then...
        self.assertEqual(["Yet another phrase we're going to change.",
                          4,
                          "This one we won't"],
                         v)


if __name__ == '__main__':
    unittest.main()
