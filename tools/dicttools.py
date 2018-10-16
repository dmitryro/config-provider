

def dictpath(dictionary: dict, path: list):
    """
    Find the node within a dictionary described by the path list.
    """
    if not path or type(dictionary) != dict:
        return dictionary
    else:
        return dictpath(dictionary[path.pop(0)], path)


def dictiter(arg):
    if isinstance(arg, dict):
        return iter(arg.items())
    elif isinstance(arg, list):
        return enumerate(arg)
    else:
        raise TypeError("Not iterable as dictionary.")


def dictwalk(arg, func: callable, path: tuple = None):
    if path is None:
        path = ()

    if type(arg) in (list, dict):
        for k, v in dictiter(arg):
            loop_path = path + (k,)

            if type(v) in (list, dict):
                dictwalk(v, func, loop_path)
            else:
                arg[k] = func(k, v, loop_path)
    else:
        raise TypeError("Not walkable as dictionary.")


def dictsort(arg):
    def sort_lists(k, v, path):
        if isinstance(k, list):
            return sorted(v)

        return v

    return dictwalk(arg, sort_lists)
