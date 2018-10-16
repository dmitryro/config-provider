

# TODO: A class cannot extend another class when using this as meta.
class Singleton(type):
    """
    As the metaclass of a class, it turns it into a singleton.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)

        return cls._instances[cls]
