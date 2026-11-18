import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

import build_site
import mathdb as m
import mathdb_server as server
from test_mathdb import concept,source,edge


class BuildSiteTests(unittest.TestCase):
    def test_static_build_matches_state_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite'
            with closing(m.connect(path)) as db:
                m.initialize(db)
                m.ingest(db,dict(sources=[source()],concepts=[concept(x) for x in ('a','b')],dependencies=[edge('a','b')]))
                expected=server.read_api(db,['state'],{})
            out=Path(temp)/'site'
            stats=build_site.build(path,out)
            self.assertEqual(stats['active_concepts'],2)
            self.assertEqual(json.loads((out/'state.json').read_text()),expected)
            index=(out/'index.html').read_text()
            self.assertIn('<html lang="en" class="static-site">',index)
            for name in build_site.ASSETS:
                self.assertIn(f'"{name}"',index)
                self.assertTrue((out/name).is_file())
            self.assertTrue((out/'.nojekyll').is_file())


if __name__=='__main__':
    unittest.main()
