import json
import unittest

from PIL import Image

from imagescope import AnalyzerError
from imagescope.backends.ollama import describe_image, JSON_PREFIX
from imagescope.profiles.wallpaper import validate_description, clean_description


class WallpaperTests(unittest.TestCase):
    def description(self, caption):
        return dict(caption=caption, subjects=[], medium='abstract', mood=[],
                    lighting=[], composition=[], tags=[], text_present=False,
                    watermark_present=False)

    def infer(self, value, continuation=False):
        content = json.dumps(value)
        if continuation:
            content = content[len(JSON_PREFIX):]
        return describe_image(Image.new('RGB', (8, 8)), 'test',
                              transport=lambda *_: {'message': {'content': content}})

    def test_blank_captions_rejected_by_validator_and_backend(self):
        for caption in ('', ' \t\r\n', '\u00a0\u2003\u202f\u3000'):
            with self.subTest(caption=repr(caption)):
                value = self.description(caption)
                with self.assertRaises(ValueError):
                    validate_description(value)
                for continuation in (False, True):
                    with self.assertRaises(AnalyzerError) as caught:
                        self.infer(value, continuation)
                    self.assertEqual(caught.exception.code, 'invalid_response')

    def test_caption_trimming_and_empty_label_arrays(self):
        value = self.description('\u2003 A red  field. \n')
        self.assertIs(validate_description(value), value)
        expected = self.description('A red  field.')
        self.assertEqual(clean_description(value), expected)
        for continuation in (False, True):
            cleaned, diagnostics = self.infer(value, continuation)
            self.assertEqual(cleaned, expected)
            self.assertEqual(diagnostics['vision_raw'], value)
