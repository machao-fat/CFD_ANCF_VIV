import unittest
from src.coupling.stage4f_d_e3_entry_review_v1.review import build
class TestReview(unittest.TestCase):
 def test_parent(self): self.assertEqual(build()['parent_status'],'accepted_scope_limited')
