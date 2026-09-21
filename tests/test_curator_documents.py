import os
from pathlib import Path
import re
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
# curator-run executes on import (it is a script, not a module), so the conversion helpers
# are lifted out by their own source markers and exercised in isolation. That is the whole
# of the new logic; the gate change itself is one identifier.
def helpers(pdftotext=None,textutil='/usr/bin/textutil'):
 src=(ROOT/'bin/curator-run').read_text()
 start=src.index('# ---- documents the judge could not previously read ----')
 block=src[start:src.index('\ndef _excerpt(',start)]
 # mirrors curator-run's own module-level imports, which the block relies on
 ns={'os':os,'re':re,'subprocess':subprocess}
 exec(compile(block,'curator-run-helpers','exec'),ns)
 ns['PDFTOTEXT']=pdftotext;ns['TEXTUTIL']=textutil
 return ns
class JudgeableSources(unittest.TestCase):
 def test_plain_text_is_unchanged_and_never_converted(self):
  h=helpers()
  for name in ('note.md','notes.txt','UPPER.MD'):
   self.assertTrue(h['_judgeable'](name));self.assertIsNone(h['_convertible'](name))
 def test_documents_become_judgeable_by_the_right_converter(self):
  # textutil reads txt/rtf/html/doc/docx/odt/wordml only. Asked for a pptx it exits 0 and
  # returns nothing, so those route to the stdlib zip reader instead.
  h=helpers()
  for name,want in (('agreement.docx','textutil'),('clip.html','textutil'),('memo.rtf','textutil'),
                    ('deck.pptx','ooxml'),('sheet.xlsx','ooxml')):
   self.assertEqual(h['_convertible'](name),want,name)
   self.assertTrue(h['_judgeable'](name),name)
 def test_ooxml_text_comes_out_of_a_real_deck_and_workbook(self):
  import zipfile,tempfile
  with tempfile.TemporaryDirectory() as tmp:
   deck=Path(tmp)/'d.pptx'
   with zipfile.ZipFile(deck,'w') as z:
    z.writestr('ppt/slides/slide1.xml','<p><a:t>Funding &amp; design</a:t><a:t>Second run</a:t></p>')
   got=helpers()['_source_text'](str(deck))
   self.assertIn('Funding & design',got);self.assertIn('Second run',got)
   book=Path(tmp)/'b.xlsx'
   with zipfile.ZipFile(book,'w') as z:
    z.writestr('xl/worksheets/sheet1.xml','<r><is><t>Inline cell</t></is></r>')
   self.assertIn('Inline cell',helpers()['_source_text'](str(book)))
 def test_a_deck_that_is_not_a_zip_yields_empty(self):
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
   bad=Path(tmp)/'broken.pptx';bad.write_bytes(b'not a zip at all')
   self.assertEqual(helpers()['_source_text'](str(bad)),'')
 def test_a_format_with_no_converter_on_this_machine_is_not_a_candidate(self):
  # Fail closed: unjudged and honest beats judged as mojibake. open(errors="ignore") on a
  # .docx yields zip noise, and that noise would reach the judge and the injection screen.
  h=helpers(pdftotext=None)
  self.assertIsNone(h['_convertible']('paper.pdf'))
  self.assertFalse(h['_judgeable']('paper.pdf'))
  h2=helpers(pdftotext='/opt/homebrew/bin/pdftotext')
  self.assertEqual(h2['_convertible']('paper.pdf'),'pdftotext')
  self.assertTrue(h2['_judgeable']('paper.pdf'))
 def test_binaries_and_config_stay_invisible(self):
  h=helpers(pdftotext='/opt/homebrew/bin/pdftotext')
  for name in ('shot.png','icon.svg','state.json','rows.csv','tool.py','app.ts','run.log','bundle.zip'):
   self.assertFalse(h['_judgeable'](name),name)
 def test_a_real_document_converts_to_its_words(self):
  if not os.path.exists('/usr/bin/textutil'):self.skipTest('textutil is macOS only')
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'clip.html'
   p.write_text('<html><body><h1>Quadratic funding</h1><p>Matching pool design.</p></body></html>')
   got=helpers()['_source_text'](str(p))
   self.assertIn('Quadratic funding',got);self.assertIn('Matching pool',got)
   self.assertNotIn('<html>',got)
   self.assertEqual(helpers()['_source_text'](str(p),9),got[:9])
 def test_an_unreadable_or_failing_conversion_yields_empty_not_garbage(self):
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
   bad=Path(tmp)/'broken.docx';bad.write_bytes(b'\x00\x01not a real docx\xff')
   self.assertEqual(helpers()['_source_text'](str(bad)),'')
   self.assertEqual(helpers()['_source_text'](str(Path(tmp)/'missing.md')),'')
if __name__=='__main__':unittest.main()
