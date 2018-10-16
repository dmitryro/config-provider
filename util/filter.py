
'''
Utility functions for working with filter expressions
'''
import re


range_pattern = None
string_pattern = None

def build_op_expr(filter_str):
    '''
    Return an (operator, value) tuple for the filter string

   (This is a work-around to shoehorn additional operators into
    querystring args.)
    '''
    # The lambda is so we can strip the first character from the
    # value string if it's one of the recognized operators.
    global range_pattern
    global string_pattern

    expr = ({
        '[]': ('is', None),
        '![]': ('is not', None),
        'true': ('is', True),
        'false': ('is', False)
    }).get(filter_str)

    if expr is None:
        if range_pattern is None:
            range_pattern = re.compile(r'^(\[|\()(?:(\d+)\.\.|\.\.(\d+)|(\d+)\.\.(\d+))(]|\))$')

        match = range_pattern.match(filter_str)

        if match:
            open, start, end, range_start, range_end, close = match.groups()

            parse_delim = lambda x: ({'[': '>=', '(': '>', ']': '<=', ')': '<'}).get(x)

            if start:
                return (parse_delim(open), int(start))
            elif end:
                return (parse_delim(close), int(end))
            elif range_start and range_end:
                # N.B: This is a somewhat-nasty hack to get a compound expression
                # into the list of filters. Any filter consumer has to be able
                # to handle it as a special case (in the case of the `retrieve_filtered`
                # service method, we just split it into two separate comparisons)
                return ('and',
                        ((parse_delim(open), int(range_start)),
                        (parse_delim(close), int(range_end))))
        else:
            if string_pattern is None:
                string_pattern = re.compile(r'^(\^?)([^$]*)(\$?)$')

            match = string_pattern.match(filter_str)

            if match:
                return ('==', filter_str)
    else:
        return expr
