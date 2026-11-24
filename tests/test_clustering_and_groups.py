import tempfile
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.database as db
from backend.database import (
    connect,
    init_db,
    list_complaint_groups,
    get_complaint_group,
    get_complaint_by_id,
    create_complaint
)
from backend.clustering import (
    haversine_distance_meters,
    calculate_geographic_proximity,
    calculate_semantic_similarity,
    calculate_composite_similarity,
    process_complaint_clustering,
    cluster_all_unassigned_complaints
)
from backend.main import (
    process_new_complaint,
    get_groups,
    get_group,
    change_group_status,
    track_complaint,
    GroupStatusUpdate
)


class TestDuplicateClusteringAndGrouping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_db = Path(cls.temp_dir.name) / "test_civic.db"
        db.DB_PATH = cls.temp_db
        init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_haversine_distance(self):
        # MG Road to Brigade Road (approx 250-400 meters)
        d = haversine_distance_meters(12.9750, 77.6080, 12.9730, 77.6070)
        self.assertIsNotNone(d)
        self.assertTrue(100 < d < 600, f"Distance expected ~250m, got {d}")

    def test_02_geographic_proximity_scoring(self):
        # Identical location
        score_exact = calculate_geographic_proximity(12.975, 77.608, "Ward 42", "5th Main", 12.975, 77.608, "Ward 42", "5th Main")
        self.assertEqual(score_exact, 1.0)

        # Far away (> 5km, e.g. Whitefield vs Malleshwaram)
        score_far = calculate_geographic_proximity(12.970, 77.500, "Ward 10", "Malleshwaram", 12.970, 77.750, "Ward 85", "Whitefield")
        self.assertEqual(score_far, 0.0)

        # Missing GPS, same ward
        score_ward = calculate_geographic_proximity(None, None, "Ward 42", "", None, None, "Ward 42", "")
        self.assertEqual(score_ward, 0.70)

    def test_03_semantic_similarity(self):
        # Two citizens describing the same garbage dump
        t1, d1 = "Piles of trash accumulating", "Large garbage dump near metro station emitting foul smell for days"
        t2, d2 = "Garbage not cleared", "Trash and waste dumped by road near metro gate creating horrible stench"
        score = calculate_semantic_similarity(t1, d1, t2, d2, category="Garbage & waste")
        self.assertTrue(score > 0.40, f"Expected strong semantic similarity, got {score}")

        # Completely different issue
        t3, d3 = "Streetlight flickering", "Pole light blinks continuously at night"
        diff_score = calculate_semantic_similarity(t1, d1, t3, d3, category="Garbage & waste")
        self.assertTrue(diff_score < score)

    def test_04_composite_similarity_category_guard(self):
        # Pothole vs Streetlight at exact same coordinates should NOT match
        c1 = {"category": "Roads & potholes", "title": "Pothole", "description": "Big hole", "latitude": 12.97, "longitude": 77.60}
        c2 = {"category": "Streetlights", "title": "Dark street", "description": "No light", "latitude": 12.97, "longitude": 77.60}
        score, details = calculate_composite_similarity(c1, c2)
        self.assertEqual(score, 0.0)
        self.assertFalse(details["category_match"])

    def test_05_complaint_submission_and_auto_clustering(self):
        # Citizen 1 reports a pothole on 100ft road Indiranagar
        lat, lon = 12.97189, 77.64115
        item1 = process_new_complaint(
            title="Massive dangerous pothole on 100ft road",
            description="Deep crater near the 12th main junction damaging vehicle suspensions.",
            category="Roads & potholes",
            priority="High",
            latitude=lat,
            longitude=lon,
            address="100 Ft Rd, Indiranagar, Bengaluru"
        )
        self.assertTrue(item1.get("group_id"))
        group_id_1 = item1["group_id"]
        group_ref_1 = item1["group_reference"]
        self.assertEqual(item1["complaints_count"], 1)

        # Citizen 2 reports the same pothole nearby with different wording
        item2 = process_new_complaint(
            title="Severe road damage crater",
            description="Huge pothole on road near 100 feet road junction, two-wheelers slipping and skidding.",
            category="Roads & potholes",
            priority="Urgent",
            latitude=lat + 0.0003,
            longitude=lon + 0.0002,
            address="Near 12th main signal, 100ft Road"
        )

        # MUST be clustered into the same consolidated issue!
        self.assertEqual(item2["group_id"], group_id_1, f"Expected same group {group_id_1}, got {item2['group_id']}")
        self.assertEqual(item2["group_reference"], group_ref_1)
        self.assertEqual(item2["complaints_count"], 2)
        self.assertTrue(item2["is_duplicate"])

        # Fetch group details via API
        grp = get_group(group_id_1)
        self.assertEqual(grp["complaints_count"], 2)
        self.assertEqual(len(grp["complaints"]), 2)
        self.assertIn(item1["reference"], grp["linked_references"])
        self.assertIn(item2["reference"], grp["linked_references"])

    def test_06_resolution_synchronization_and_notifications(self):
        # Create a group by submitting complaints
        lat, lon = 12.9352, 77.6245  # Koramangala
        r1 = process_new_complaint(
            title="Water leakage from BWSSB main pipe",
            description="Potable drinking water gushing onto the road near 5th block.",
            category="Water supply",
            priority="High",
            latitude=lat,
            longitude=lon,
            address="5th Block, Koramangala"
        )

        r2 = process_new_complaint(
            title="Burst pipeline wasting clean water",
            description="Severe pipeline leak flooding street opposite commercial complex.",
            category="Water supply",
            priority="Medium",
            latitude=lat + 0.0002,
            longitude=lon + 0.0001,
            address="5th Block Main Road, Koramangala"
        )

        group_id = r1["group_id"]
        self.assertEqual(r2["group_id"], group_id)

        # Admin resolves the consolidated issue
        body = GroupStatusUpdate(
            status="Resolved",
            remarks="BWSSB field team replaced the burst valve and restored water pressure.",
            assigned_department="BWSSB South Division",
            assigned_officer="Assistant Executive Engineer Ramesh"
        )
        updated_group = change_group_status(group_id, body)
        self.assertEqual(updated_group["status"], "Resolved")

        # Verify linked complaints received the status synchronization
        c1 = get_complaint_by_id(r1["id"])
        c2 = get_complaint_by_id(r2["id"])
        self.assertEqual(c1["status"], "Resolved")
        self.assertEqual(c2["status"], "Resolved")

        # Verify citizen tracking API returns consolidated group & notification
        track_data = track_complaint(r1["reference"])
        self.assertEqual(track_data["status"], "Resolved")
        self.assertIsNotNone(track_data.get("group"))
        self.assertEqual(track_data["group"]["complaints_count"], 2)

        # Check notifications
        notifications = track_data.get("notifications", [])
        self.assertTrue(len(notifications) > 0)
        self.assertEqual(notifications[0]["notification_type"], "issue_resolved")
        self.assertIn("resolved", notifications[0]["message"].lower())

    def test_07_concurrency_safe_grouping(self):
        import concurrent.futures
        # Create 6 complaints concurrently for the same streetlight issue
        lat, lon = 12.9800, 77.5900
        prefix = uuid.uuid4().hex[:6]
        def create_and_cluster(idx):
            comp = create_complaint({
                "reference": f"TEST-CONCUR-{prefix}-{idx}",
                "title": f"Streetlight outage near circle #{idx}",
                "description": "Dark street due to non-functioning sodium vapor lamp on pole.",
                "category": "Streetlights",
                "priority": "Medium",
                "latitude": lat + (idx * 0.00005),
                "longitude": lon + (idx * 0.00005),
                "address": "Shivajinagar Circle",
                "location_source": "test"
            })
            grp = process_complaint_clustering(comp["id"])
            return grp

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            groups = list(executor.map(create_and_cluster, range(6)))

        group_ids = {g["id"] for g in groups}
        self.assertEqual(len(group_ids), 1, f"Expected 1 unique group, got {len(group_ids)}: {group_ids}")

        target_gid = list(group_ids)[0]
        grp = get_complaint_group(target_gid)
        self.assertEqual(grp["complaints_count"], 6)

    def test_08_api_groups_listing(self):
        res = get_groups()
        self.assertIn("groups", res)
        self.assertIn("total_groups", res)
        self.assertIn("total_citizens", res)
        self.assertIn("multi_report_groups", res)
        self.assertTrue(res["total_groups"] > 0)
        self.assertTrue(res["total_citizens"] >= res["total_groups"])

    def test_09_same_location_typo_clustering(self):
        # Two citizens reporting potholes at the same location with citizen typos
        c1 = create_complaint({
            "reference": "CR-TEST-ARAMANE-1",
            "title": "big potgole hugee",
            "description": "it is a safety issue",
            "category": "Roads & potholes",
            "priority": "High",
            "ward_name": "Aramane Nagara",
            "address": "Snap Fitness, 36, 4th Main Road, ITI Colony, Aramane Nagara",
            "latitude": 13.0309297,
            "longitude": 77.570022
        })
        g1 = process_complaint_clustering(c1["id"])
        self.assertIsNotNone(g1)

        c2 = create_complaint({
            "reference": "CR-TEST-ARAMANE-2",
            "title": "largeee pothole",
            "description": "-",
            "category": "Roads & potholes",
            "priority": "Medium",
            "ward_name": "Aramane Nagara",
            "address": "Snap Fitness, 36, 4th Main Road, ITI Colony, Aramane Nagara",
            "latitude": 13.0309297,
            "longitude": 77.570022
        })
        g2 = process_complaint_clustering(c2["id"])
        self.assertIsNotNone(g2)
        self.assertEqual(g1["id"], g2["id"], f"Expected complaints to club into same group, got {g1['id']} vs {g2['id']}")
        self.assertGreaterEqual(g2["complaints_count"], 2)


if __name__ == "__main__":
    unittest.main()
