"""Distinguish IEEE style controls from bibliographic records."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_references.py'
spec = importlib.util.spec_from_file_location('spanlife_bibliography', SOURCE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

ENTRY = '@misc{source,\n author={Fixture Author},\n title={Example Record},\n year={2025}\n}\n'

class BibliographyControlTests(unittest.TestCase):
    def test_ieee_style_control_is_not_a_reference(self):
        control = '@IEEEtranBSTCTL{authorDisplay,\n CTLdash_repeated_names={no}\n}\n'
        self.assertEqual(set(audit.parse_bib(control + ENTRY)), {'source'})
        self.assertEqual(audit.parse_bib(control), {})

    def test_duplicate_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate BibTeX key'):
            audit.parse_bib(ENTRY + ENTRY)

    def test_missing_or_blank_real_title_remains_invalid(self):
        for fields in ({'author': 'Fixture Author', 'year': '2025'},
                       {'author': 'Fixture Author', 'title': ' ', 'year': '2025'}):
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(ValueError, 'title'):
                    audit.require_bibliographic_fields('source', fields)

if __name__ == '__main__':
    unittest.main()
