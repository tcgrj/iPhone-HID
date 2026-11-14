import unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from wireless.console.screen import ScreenFrame
from wireless.console.lesson import enabled_check

class ButtonTests(unittest.TestCase):
    def frame(self,color):
        output=BytesIO();Image.new('RGB',(800,600),color).save(output,'JPEG')
        return ScreenFrame(1,0,output.getvalue(),800,600)
    def test_ocr_variant_on_enabled_planned_button(self):
        with patch('wireless.console.lesson.read_regions',return_value=[('检査',.3,(362,545))]):
            self.assertTrue(enabled_check(self.frame((70,200,20)),(0,0,1,1),(362,545)))
            self.assertFalse(enabled_check(self.frame((180,180,180)),(0,0,1,1),(362,545)))
            self.assertFalse(enabled_check(self.frame((70,200,20)),(0,0,1,1),(362,400)))
    def test_other_green_buttons_rejected(self):
        with patch('wireless.console.lesson.read_regions',return_value=[('购买',1,(362,545))]):
            self.assertFalse(enabled_check(self.frame((70,200,20)),(0,0,1,1),(362,545)))
