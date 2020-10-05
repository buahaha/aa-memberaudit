from esi.clients import EsiClientProvider

from .utils import get_swagger_spec_path

esi = EsiClientProvider(spec_file=get_swagger_spec_path())
