import json
import unittest

from tests.support import AppCase


class WeightedSampleProfileTests(AppCase, unittest.TestCase):
    def test_profile_reports_material_periods_and_three_way_strata(self):
        record = {
            "story_id": "tale-a", "revision": 1, "title": "Tale",
            "tradition": "river", "material_period": "early",
            "source": {"reference": "card", "kind": "book"},
            "characters": [{"character_id": "one", "name": "One", "sibling_order": 1}],
            "events": [{"event_id": "e1", "sequence": 1, "actor_id": "one",
                        "action": "act", "consequence": "result", "evidence": "text"}],
        }
        legacy = json.loads(json.dumps(record))
        legacy["story_id"] = "tale-b"
        legacy.pop("material_period")
        self.app.import_batch({"batch_id": "profile", "stories": [record, legacy]})
        profile = self.app.create_report()["sample_profile"]
        self.assertEqual(profile["material_periods"], {"early": 1, "unspecified": 1})
        self.assertEqual(profile["strata"], {
            "river | book | early": 1,
            "river | book | unspecified": 1,
        })


if __name__ == "__main__":
    unittest.main()
