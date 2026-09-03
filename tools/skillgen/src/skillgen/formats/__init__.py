"""Inference formats: how a model is asked to express a user interface."""

from .direct_json import DirectJsonFormat
from .express import ExpressFormat

__all__ = ["DirectJsonFormat", "ExpressFormat"]
