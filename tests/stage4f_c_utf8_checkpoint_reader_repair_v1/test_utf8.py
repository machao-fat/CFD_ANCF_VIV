import json, tempfile, unittest
from pathlib import Path
from coupling.stage4f_c_utf8_checkpoint_reader_repair_v1.utf8 import *

class UTF8Tests(unittest.TestCase):
 def test_roundtrip_unicode_and_integer(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'中文.json'; write_json(p,{'path':'中文/Δ','mtime_ns':2**80,'tau':'0.023728053952574758'}); x=read_json(p)
   self.assertEqual(x['mtime_ns'],2**80); self.assertEqual(x['path'],'中文/Δ')
 def test_reject_bom_and_invalid(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x'; p.write_bytes(b'\xef\xbb\xbf{}')
   with self.assertRaises(UTF8BoundaryError): read_json(p)
   p.write_bytes(b'{"x":"\xC3"}')
   with self.assertRaises(UTF8BoundaryError): read_json(p)
 def test_jsonl(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x'; p.write_bytes('{"p":"中文"}\n'.encode('utf-8')); self.assertEqual(read_jsonl(p)[0]['p'],'中文')
 def test_canonical_stable(self):
  self.assertEqual(canonical_bytes({'b':'中文','a':2}),canonical_bytes({'a':2,'b':'中文'}))

if __name__=='__main__': unittest.main()
