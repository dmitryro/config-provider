"""
Configuration Provider
@author dmitry.r
"""

import yaml, os
from meta.ioc import Importer
from util.loader import Loader
from service.provider import ServiceProvider


class ConfigProvider(ServiceProvider):
    """ Basic configuration provider """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.importer = Importer()
        self.service_classes = {}
        self.app_conf = {}
        self.app_conf_path = kwargs.get('app_conf') or os.environ.get('APP_CONFIG_PATH', '../config.yaml')
        self.service_conf_path = os.environ.get('SERVICE_CONFIG_PATH', '../configs/service_conf.yaml')

        with open(self.service_conf_path, 'r') as fp:
            self.service_conf = yaml.load(fp.read(), Loader)

        with open(self.app_conf_path, 'r') as fp:
            self.settings = yaml.load(fp.read(), Loader)

        self.app_conf = self.settings

    def value(self, key):
        return self.locate_value(self.settings, key)[0]

    def set_value(self, path, value):
        parts = path.split('.')
        last_level = self.app_conf

        for i in range(0, len(parts) - 1):
            if parts[i] not in last_level:
                last_level[parts[i]] = {}
            last_level = last_level[parts[i]]
        last_level[parts.pop()] = value

    def get_value(self, path, default=None):
        try:
            return self._get_conf(path)
        except Exception as e:
            return default

    def locate_value(self, search_dict, field):
        """
        Takes a dict with nested lists and dicts,
        and searches all dicts for a key of the field
        provided.
        """
        fields_found = []

        for key, value in search_dict.items():

            if key == field:
                fields_found.append(value)

            elif isinstance(value, dict):
                results = self.locate_value(value, field)
                for result in results:
                    fields_found.append(result)

            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        more_results = self.locate_value(item, field)
                        for another_result in more_results:
                            fields_found.append(another_result)

        return fields_found
