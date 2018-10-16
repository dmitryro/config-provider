

class BadRowError(Exception):

    pass


class CsvParser():

    SEPARATOR = ','
    BAD_ROW_ERRMSG = 'All rows need to have the same amount of columns as the headers.'

    def dump(self, headers: tuple, rows: tuple, separator: str = SEPARATOR, wrapper: str = None) -> str:
        if not len(rows):
            return ''

        column_count = len(headers)
        lines = [self._join_row(headers, separator, wrapper)]

        for row in rows:
            if len(row) != column_count:
                raise BadRowError(self.BAD_ROW_ERRMSG)

            lines.append(self._join_row(row, separator, wrapper))

        return "\n".join(lines)

    @classmethod
    def _join_row(cls, row: tuple, separator: str, wrapper: str = None):
        return separator.join(cell is not None and cls._wrap_cell(cell, wrapper) or '' for cell in row)

    @staticmethod
    def _wrap_cell(cell: str, wrapper: str = None):
        return wrapper is None and str(cell) or f'{wrapper}{cell}{wrapper}'

