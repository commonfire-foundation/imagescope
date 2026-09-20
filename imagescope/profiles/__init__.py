"""Explicit built-in task profiles; no registration or dynamic plugin loading."""
from dataclasses import dataclass
from typing import Callable
from types import MappingProxyType

from . import general, wallpaper


@dataclass(frozen=True)
class Profile:
    name: str
    version: str
    prompt: str
    schema: dict
    validate: Callable
    clean: Callable
    summary_field: str
    labels: tuple[tuple[str, str], ...]
    flags: tuple[tuple[str, str], ...]

    @property
    def json_prefix(self):
        return '{"' + self.summary_field + '":'


PROFILES = MappingProxyType({
    'wallpaper': Profile('wallpaper', wallpaper.PROMPT_VERSION, wallpaper.VISION_PROMPT,
                         wallpaper.SCHEMA, wallpaper.validate_description, wallpaper.clean_description,
                         'caption', (('subjects', 'Subjects'), ('medium', 'Medium'), ('mood', 'Mood'),
                                     ('lighting', 'Lighting'), ('composition', 'Composition'), ('tags', 'Tags')),
                         (('text_present', 'text'), ('watermark_present', 'watermark'))),
    'general': Profile('general', general.PROMPT_VERSION, general.VISION_PROMPT,
                       general.SCHEMA, general.validate_description, general.clean_description,
                       'summary', (('subjects', 'Subjects'),), (('text_present', 'text'),)),
})


def get_profile(name):
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError(f'Unknown profile: {name!r}; choose {", ".join(PROFILES)}')
    return PROFILES[name]
