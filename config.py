import yaml


class TTYGConfig:
    """Provides the TTYG client config."""

    def __init__(self, config_file):
        with open(config_file, "r", encoding="utf-8") as file:
            self._config = yaml.safe_load(file)

    @property
    def openai_apikey(self):
        return self._config.get('openai', {}).get('api_key')

    @property
    def openai_url(self):
        return self._config.get('openai', {}).get('api_url')

    @property
    def openai_azure_api_version(self):
        return self._config.get('openai', {}).get('azure_api_version')

    @property
    def graphdb_url(self):
        return self._config.get('graphdb', {}).get('url')

    @property
    def graphdb_username(self):
        return self._config.get('graphdb', {}).get('username')

    @property
    def graphdb_password(self):
        return self._config.get('graphdb', {}).get('password')

    @property
    def graphdb_auth_header(self):
        return self._config.get('graphdb', {}).get('auth_header')

    @property
    def graphdb_installation_id(self):
        return self._config.get('graphdb', {}).get('installation_id')
