import unittest
class Tests(unittest.TestCase):
 def test_same_source(self): self.assertEqual((10,30),(10,30))
 def test_threshold(self): self.assertEqual(1e-11,1e-11)
