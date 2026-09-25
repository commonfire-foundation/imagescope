"""Stateless local image analysis. No Qt or database dependency."""
from .contracts import AnalysisRequest, AnalyzerError

__version__ = '0.1.0rc2'
__all__ = ['AnalysisRequest', 'AnalyzerError', 'analyze', 'MetadataRequest', 'inspect_metadata']


def __getattr__(name):
    if name == 'analyze':
        from .api import analyze
        return analyze
    if name in ('MetadataRequest', 'inspect_metadata'):
        from .metadata import MetadataRequest, inspect_metadata
        return {'MetadataRequest': MetadataRequest, 'inspect_metadata': inspect_metadata}[name]
    raise AttributeError(name)
