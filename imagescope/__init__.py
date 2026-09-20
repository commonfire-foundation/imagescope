"""Stateless local image analysis. No Qt or database dependency."""
from .contracts import AnalysisRequest, AnalyzerError

__version__ = '0.1.0rc1'
__all__ = ['AnalysisRequest', 'AnalyzerError', 'analyze']


def __getattr__(name):
    if name == 'analyze':
        from .api import analyze
        return analyze
    raise AttributeError(name)
