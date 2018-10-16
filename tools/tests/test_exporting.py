import unittest

from ..exporting import CsvParser


GOT_CSV = """name,house,demise
Robert,Baratheon,Very
Tyrion,Lannister,Doubtful
Jon,Stark,Please"""

GOT_CSV_WRAPPERS = '''"name";"house";"demise"
"Robert";"Baratheon";"Very"
"Tyrion";"Lannister";"Doubtful"
"Jon";"Stark";"Please"'''

GOT_CSV_NULLS = '''"name";"house";"demise"
"Robert";"Baratheon";"Very"
"Tyrion";"Lannister";"Doubtful"
"Jon";;"Please"'''


class CsvParserTest(unittest.TestCase):

    maxDiff = None

    def test_dumping_csv(self):
        # Given...
        document = (('Robert', 'Baratheon', 'Very'),
                    ('Tyrion', 'Lannister', 'Doubtful'),
                    ('Jon', 'Stark', 'Please'))
        # When...
        actual = CsvParser().dump(('name', 'house', 'demise'), document)
        # Then...
        expected = GOT_CSV
        self.assertEqual(expected, actual)

    def test_dumping_empty_csv(self):
        # Given...
        document = tuple()
        # When...
        actual = CsvParser().dump(('name', 'house', 'demise'), document)
        # Then...
        expected = ''
        self.assertEqual(expected, actual)

    def test_dumping_csv_with_wrappers(self):
        # Given...
        document = (('Robert', 'Baratheon', 'Very'),
                    ('Tyrion', 'Lannister', 'Doubtful'),
                    ('Jon', 'Stark', 'Please'))
        # When...
        actual = CsvParser().dump(('name', 'house', 'demise'), document, ';', '"')
        # Then...
        expected = GOT_CSV_WRAPPERS
        self.assertEqual(expected, actual)

    def test_dumping_csv_with_nulls(self):
        # Given...
        document = (('Robert', 'Baratheon', 'Very'),
                    ('Tyrion', 'Lannister', 'Doubtful'),
                    ('Jon', None, 'Please'))
        # When...
        actual = CsvParser().dump(('name', 'house', 'demise'), document, ';', '"')
        # Then...
        expected = GOT_CSV_NULLS

        self.assertEqual(expected, actual)
