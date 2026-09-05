import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tests.notion_fake import EDIT, FakeClient, hid, image, para, rt, toggle  # noqa: E402
from notion_mirror.config import Config  # noqa: E402
from notion_mirror.mirror import Mirror  # noqa: E402
from notion_mirror.state import State  # noqa: E402

LATER = "2026-09-02T00:00:00.000Z"
SCHEMA = {"Name": {"type": "title"}, "Status": {"type": "select"}}


def workspace(tmp, **over):
    """A vault with a lane and a state dir, plus a small connected tree:
    1 Root > 2 Music (paragraph + image + toggle 22 holding paragraph 23) > 3 LW Songs [db, ds 30]
    > rows 4 Alive, 5 Atlantic > 6 Lyrics under Alive."""
    vault = Path(tmp) / "vault"
    lane = vault / "raw" / "tools" / "Notion"
    lane.mkdir(parents=True)
    (lane / "LANE.md").write_text("---\nlane: Notion\n---\n")
    state_dir = Path(tmp) / "state"
    cfg = Config(token="t", version="2026-03-11", brain_root=vault, lane_dir=lane, state_dir=state_dir, files="fetch",
                 shrink_floor=90, allow_shrink=False, default_root="Private & Shared", required_roots={hid(1): "Private & Shared"})
    for k, v in over.items():
        setattr(cfg, k, v)
    c = FakeClient()
    c.add_page(1, "Root", c.workspace())
    c.files["https://s3/shot.png?sig=1"] = b"PNG"
    c.add_page(2, "Music", c.under(1), body=[para(20, "All the songs."), image(21, "https://s3/shot.png?sig=1"), toggle(22, "More")])
    c.blocks[hid(22)] = [para(23, "hidden verse")]
    c.add_database(3, 30, "LW Songs", c.under(2), SCHEMA)
    c.add_row(4, 3, 30, "Alive", {"Status": {"type": "select", "select": {"name": "IP"}}}, body=[para(40, "verse")])
    c.add_row(5, 3, 30, "Atlantic", {"Status": {"type": "select", "select": None}})
    c.add_page(6, "Lyrics", c.under(4), body=[para(60, "words")])
    return cfg, c, lane


def paths_of(lane):
    return sorted(str(p.relative_to(lane)) for p in lane.rglob("*") if p.is_file())


P1 = "Private & Shared/Root %s.md" % hid(1)
P2 = "Private & Shared/Root/Music %s.md" % hid(2)
P3 = "Private & Shared/Root/Music/LW Songs %s_all.csv" % hid(3)
P4 = "Private & Shared/Root/Music/LW Songs/Alive %s.md" % hid(4)
P5 = "Private & Shared/Root/Music/LW Songs/Atlantic %s.md" % hid(5)
P6 = "Private & Shared/Root/Music/LW Songs/Alive/Lyrics %s.md" % hid(6)
IMG = "Private & Shared/Root/Music/shot.png"


class FullRun(unittest.TestCase):
    def test_full_writes_the_export_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            m = Mirror(client, cfg, State(cfg.state_dir))
            rep = m.full()
            self.assertEqual(rep.errors, [])
            self.assertIsNone(rep.refused)
            self.assertEqual(paths_of(lane), sorted(["LANE.md", P1, P2, P3, P4, P5, P6, IMG]))
            self.assertEqual((lane / P4).read_text(), "# Alive\n\nStatus: IP\n\nverse\n")
            self.assertEqual((lane / P3).read_text(), "\ufeffName,Status\nAlive,IP\nAtlantic,\n")
            music = (lane / P2).read_text()
            self.assertIn("All the songs.", music)
            self.assertIn("![shot.png](Music/shot.png)", music)
            self.assertEqual((lane / IMG).read_bytes(), b"PNG")
            self.assertEqual((lane / "LANE.md").read_text(), "---\nlane: Notion\n---\n")
            self.assertEqual(rep.written, 6)
            self.assertEqual(rep.attachments, 1)
            self.assertEqual(sorted(m.manifest.items), sorted([hid(n) for n in (1, 2, 3, 4, 5, 6)]))
            self.assertEqual(m.manifest.items[hid(4)]["cells"], ["Alive", "IP"])
            self.assertEqual(m.manifest.items[hid(3)]["header"], ["Name", "Status"])
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("OK "))
            self.assertEqual(State(cfg.state_dir).read_cursor(), EDIT)
            self.assertIsNotNone(State(cfg.state_dir).read_last_full())

    def test_full_is_idempotent_and_refetches_only_databases(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            before = client.requests
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            # nothing edited: no page is re-rendered; only the database is requeried and found unchanged
            self.assertEqual((rep.written, rep.unchanged, rep.moved, rep.deleted), (0, 1, 0, 0))
            self.assertEqual(client.queries, 2)
            self.assertEqual(client.requests - before, 3)  # search, data_source schema, query_rows

    def test_full_repairs_a_file_missing_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            (lane / P6).unlink()
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertTrue((lane / P6).exists())
            self.assertEqual(rep.written, 1)

    def test_dry_run_writes_nothing_and_reports_the_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            (lane / P1).parent.mkdir(parents=True, exist_ok=True)
            (lane / P1).write_text("# pre-existing\n")
            rep = Mirror(client, cfg, State(cfg.state_dir)).full(dry_run=True)
            self.assertEqual(paths_of(lane), sorted(["LANE.md", P1]))
            self.assertEqual((rep.oracle_total, rep.oracle_matched), (6, 1))
            self.assertIn((hid(2), P2, ""), rep.mismatches)
            self.assertEqual(len(rep.would_write), 6)
            self.assertFalse((cfg.state_dir / "state" / "manifest.json").exists())

    def test_dry_run_reports_disk_files_the_walk_did_not_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            stray = lane / ("Private & Shared/Old %s.md" % hid(77))
            stray.parent.mkdir(parents=True, exist_ok=True)
            stray.write_text("# Old\n")
            rep = Mirror(client, cfg, State(cfg.state_dir)).full(dry_run=True)
            self.assertEqual(rep.unclaimed, ["Private & Shared/Old %s.md" % hid(77)])
            self.assertEqual(rep.oracle_total, 6)
            self.assertIn("unclaimed on disk 1", rep.summary())

    def test_skip_files_mode_downloads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, files="skip")
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.attachments, 0)
            self.assertFalse((lane / IMG).exists())
            self.assertIn("![shot.png](Music/shot.png)", (lane / P2).read_text())

    def test_rename_moves_file_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.retitle(2, "Tunes", LATER)
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertFalse((lane / P2).exists())
            self.assertTrue((lane / ("Private & Shared/Root/Tunes %s.md" % hid(2))).exists())
            self.assertTrue((lane / ("Private & Shared/Root/Tunes/LW Songs %s_all.csv" % hid(3))).exists())
            self.assertTrue((lane / ("Private & Shared/Root/Tunes/LW Songs/Alive/Lyrics %s.md" % hid(6))).exists())
            self.assertFalse((lane / "Private & Shared/Root/Music").exists())
            self.assertGreaterEqual(rep.moved, 1)

    def test_a_rename_and_a_delete_in_one_walk_leave_no_stray(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, shrink_floor=50)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.retitle(2, "Tunes", LATER)
            client.pages[hid(6)]["in_trash"] = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.deleted, 1)
            self.assertEqual([p for p in paths_of(lane) if "Lyrics" in p], [])

    def test_two_nested_renames_in_one_walk_relocate_a_delete_beneath_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, shrink_floor=50)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.retitle(2, "Tunes", LATER)
            client.data_sources[hid(30)]["title"] = [rt("Hits")]
            client.data_sources[hid(30)]["last_edited_time"] = LATER
            client.pages[hid(6)]["in_trash"] = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.deleted, 1)
            self.assertEqual([p for p in paths_of(lane) if "Lyrics" in p], [])
            self.assertIn("Private & Shared/Root/Tunes/Hits/Alive %s.md" % hid(4), paths_of(lane))

    def test_a_rename_and_a_reparent_in_one_walk_leave_one_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.retitle(2, "Tunes", LATER)
            client.add_page(7, "Elsewhere", client.under(1), edited=LATER)
            client.pages[hid(6)]["parent"] = client.under(7)
            client.pages[hid(6)]["last_edited_time"] = LATER
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual([p for p in paths_of(lane) if "Lyrics" in p],
                             ["Private & Shared/Root/Elsewhere/Lyrics %s.md" % hid(6)])

    def test_trashed_row_is_deleted_and_csv_shrinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, shrink_floor=50)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.pages[hid(5)]["in_trash"] = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.deleted, 1)
            self.assertFalse((lane / P5).exists())
            self.assertEqual((lane / P3).read_text(), "\ufeffName,Status\nAlive,IP\n")
            self.assertEqual(rep.unclaimed, [])
            self.assertNotIn("unclaimed", rep.summary())

    def test_shrink_guard_refuses_then_allow_shrink_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            for n in (2, 3, 4, 5, 6):
                (client.pages if n != 3 else client.data_sources)[hid(n) if n != 3 else hid(30)]["in_trash"] = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertIsNotNone(rep.refused)
            self.assertTrue((lane / P4).exists())
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("FAILED "))
            cfg.allow_shrink = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertIsNone(rep.refused)
            self.assertEqual(paths_of(lane), sorted(["LANE.md", P1]))

    def test_errors_are_reported_and_status_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            client.fail_children_for.add(hid(2))
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(len(rep.errors), 1)
            self.assertFalse((lane / P2).exists())
            self.assertTrue((lane / P4).exists())
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("FAILED "))
            self.assertIsNone(State(cfg.state_dir).read_cursor())
            self.assertIsNone(State(cfg.state_dir).read_last_full())


    def test_a_failing_nested_block_warns_and_the_page_still_lands(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            client.fail_children_for.add(hid(22))
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(len(rep.warnings), 1)
            self.assertIn("children of toggle %s" % hid(22), rep.warnings[0])
            self.assertIn("children unavailable", (lane / P2).read_text())
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("OK "))

    def test_children_error_marker_cannot_close_the_comment_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            client.fail_children_for.add(hid(22))
            client.fail_message = "boom --> escaped the comment\n" + ("x" * 300)
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(len(rep.warnings), 1)
            self.assertIn("boom --> escaped the comment", rep.warnings[0])
            text = (lane / P2).read_text()
            self.assertEqual(text.count("<!--"), 1)
            self.assertEqual(text.count("-->"), 1)
            start = text.index("<!--")
            end = text.index("-->") + len("-->")
            marker = text[start:end]
            self.assertNotIn("boom --> escaped", marker)


class Containment(unittest.TestCase):
    """Nothing a title can say may move a write or a delete outside the lane."""

    def dotted(self, client):
        """Pages whose titles are dot-only, plus a chain of them deep enough to climb out."""
        client.add_page(10, "..", client.under(1))
        client.add_page(11, ".", client.under(1))
        client.add_page(12, "..", client.under(1))
        client.add_page(13, "..", client.under(12))
        client.add_page(14, "..", client.under(13))
        client.add_page(15, "..", client.under(14))
        return [hid(n) for n in (10, 11, 12, 13, 14, 15)]

    def test_dot_titles_never_write_outside_the_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            other = lane.parent / "OtherLane"
            other.mkdir(parents=True)
            (other / "keep.md").write_text("keep\n")
            self.dotted(client)
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            outside = [str(p.relative_to(cfg.brain_root)) for p in cfg.brain_root.rglob("*")
                       if p.is_file() and lane not in p.parents]
            self.assertEqual(outside, ["raw/tools/OtherLane/keep.md"])
            self.assertTrue((other / "keep.md").exists())
            self.assertEqual((lane / "LANE.md").read_text(), "---\nlane: Notion\n---\n")
            for path in paths_of(lane):
                self.assertNotIn("..", path.split("/"))

    def test_trashing_a_dot_title_deletes_only_its_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            other = lane.parent / "OtherLane"
            other.mkdir(parents=True)
            (other / "keep.md").write_text("keep\n")
            dotted = self.dotted(client)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            for i in dotted:
                client.pages[i]["in_trash"] = True
            cfg.allow_shrink = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertTrue(lane.is_dir())
            self.assertTrue((other / "keep.md").exists())
            self.assertEqual((lane / "LANE.md").read_text(), "---\nlane: Notion\n---\n")
            self.assertEqual(paths_of(lane), sorted(["LANE.md", P1, P2, P3, P4, P5, P6, IMG]))

    def test_a_manifest_path_outside_the_lane_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            other = lane.parent / "OtherLane"
            other.mkdir(parents=True)
            (other / "keep.md").write_text("keep\n")
            m = Mirror(client, cfg, State(cfg.state_dir))
            m.full()
            m.manifest.items[hid(90)] = {"id": hid(90), "kind": "page", "last_edited": EDIT,
                                         "path": "../OtherLane/keep.md"}
            m.manifest.save()
            cfg.allow_shrink = True
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertTrue((other / "keep.md").exists())
            self.assertEqual(rep.deleted, 0)
            self.assertTrue(any("refused, outside the lane" in e for e in rep.errors), rep.errors)


class Check(unittest.TestCase):
    def test_check_lists_roots_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, required_roots={hid(1): "Private & Shared", hid(99): "Team HQ"})
            out = Mirror(client, cfg, State(cfg.state_dir)).check()
            self.assertEqual(out["bot"], "TestBot")
            self.assertEqual(out["workspace"], "Test WS")
            self.assertEqual(out["items"], 6)
            self.assertEqual(out["kinds"], {"page": 3, "row": 2, "database": 1})
            self.assertEqual(out["roots"], {hid(1): "Root"})
            self.assertEqual(out["missing_roots"], [hid(99)])
            self.assertEqual(paths_of(lane), ["LANE.md"])


class DeltaRun(unittest.TestCase):
    def test_delta_rewrites_the_window_and_advances_the_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            stamps = {p: (lane / p).stat().st_mtime_ns for p in (P1, P3, P4, P5, P6)}
            client.blocks[hid(2)] = [para(20, "New body.")]
            client.pages[hid(2)]["last_edited_time"] = LATER
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.mode, "delta")
            self.assertEqual((rep.written, rep.errors), (1, []))
            self.assertIn("New body.", (lane / P2).read_text())
            for p, before in stamps.items():
                self.assertEqual((lane / p).stat().st_mtime_ns, before, p)
            self.assertEqual(State(cfg.state_dir).read_cursor(), LATER)
            self.assertEqual(client.queries, 1)  # only the full run queried rows

    def test_delta_picks_up_a_body_edited_inside_the_same_minute(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.blocks[hid(6)] = [para(60, "Same minute, same stamp.")]
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.written, 1)
            self.assertIn("Same minute, same stamp.", (lane / P6).read_text())

    def test_delta_row_change_rebuilds_csv_from_cells_without_requery(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.pages[hid(4)]["properties"]["Status"] = {"type": "select", "select": {"name": "Done"}}
            client.pages[hid(4)]["last_edited_time"] = LATER
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertEqual((lane / P4).read_text(), "# Alive\n\nStatus: Done\n\nverse\n")
            self.assertEqual((lane / P3).read_text(), "\ufeffName,Status\nAlive,Done\nAtlantic,\n")
            self.assertEqual(client.queries, 1)

    def test_delta_schema_change_requeries_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.data_sources[hid(30)]["properties"] = {"Name": {"type": "title"}, "Status": {"type": "select"}, "Year": {"type": "number"}}
            client.data_sources[hid(30)]["last_edited_time"] = LATER
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertTrue((lane / P3).read_text().startswith("\ufeffName,Status,Year\n"))
            self.assertEqual(client.queries, 2)

    def test_delta_new_page_under_unknown_parent_fetches_the_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.add_page(7, "Archive", client.under(1), edited="2026-08-01T00:00:00.000Z")  # older than the window
            client.add_page(8, "Deep", client.under(7), edited=LATER)
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertTrue((lane / ("Private & Shared/Root/Archive/Deep %s.md" % hid(8))).exists())

    def test_delta_error_keeps_the_cursor_and_fails_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.pages[hid(2)]["last_edited_time"] = LATER
            client.fail_children_for.add(hid(2))
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(len(rep.errors), 1)
            self.assertEqual(State(cfg.state_dir).read_cursor(), EDIT)
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("FAILED "))
            client.fail_children_for.clear()
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertEqual(State(cfg.state_dir).read_cursor(), LATER)

    def test_delta_without_cursor_runs_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.mode, "full")
            self.assertEqual(rep.written, 6)

    def test_delta_dry_run_reports_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.retitle(6, "Words", LATER)
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta(dry_run=True)
            self.assertEqual(rep.would_move, [(P6, "Private & Shared/Root/Music/LW Songs/Alive/Words %s.md" % hid(6))])
            self.assertTrue((lane / P6).exists())


if __name__ == "__main__":
    unittest.main()
