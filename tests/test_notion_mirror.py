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


    def test_a_vanished_subtree_warns_instead_of_failing(self):
        """The database's data source is what page 6's sibling rows need too (their own
        Status column comes from its schema), so losing access to it takes the whole
        subtree with it: the database, both rows, and the page nested under one of them.
        None of that may turn into a run failure."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            client.vanish_after_search.add(hid(6))
            client.vanish_after_search.add(hid(30))
            m = Mirror(client, cfg, State(cfg.state_dir))
            rep = m.full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.vanished, 4)
            self.assertEqual(len(rep.warnings), 4)
            for kind, n in (("page", 6), ("database", 3), ("row", 4), ("row", 5)):
                self.assertTrue(any("vanished during the run: %s %s" % (kind, hid(n)) in w for w in rep.warnings), rep.warnings)
            self.assertEqual(paths_of(lane), sorted(["LANE.md", P1, P2, IMG]))
            for n in (3, 4, 5, 6):
                self.assertNotIn(hid(n), m.manifest.items)
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("OK "))
            self.assertEqual(State(cfg.state_dir).read_cursor(), EDIT)
            self.assertIsNotNone(State(cfg.state_dir).read_last_full())
            self.assertIn(", vanished 4", rep.summary())

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

    def test_delta_vanished_page_deletes_the_file_and_advances_the_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertTrue((lane / P6).exists())
            client.pages[hid(6)]["last_edited_time"] = LATER
            client.vanish_after_search.add(hid(6))
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.deleted, 1)
            self.assertEqual(rep.vanished, 1)
            self.assertFalse((lane / P6).exists())
            self.assertEqual(State(cfg.state_dir).read_cursor(), LATER)

    def test_delta_dry_run_reports_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.retitle(6, "Words", LATER)
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta(dry_run=True)
            self.assertEqual(rep.would_move, [(P6, "Private & Shared/Root/Music/LW Songs/Alive/Words %s.md" % hid(6))])
            self.assertTrue((lane / P6).exists())


class Coverage(unittest.TestCase):
    def test_groups_unreachable_export_files_by_top_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            export = Path(tmp) / "export"
            for rel in (P1, P2, P4,
                        "Private & Shared/Old Tree %s.md" % hid(70),
                        "Private & Shared/Old Tree/Deep one %s.md" % hid(71),
                        "Private & Shared/Old Tree/Deep two %s.md" % hid(72),
                        "Private & Shared/Old Tree/Deep two/Deeper %s.md" % hid(73),
                        "Teamspace/Sub/Page %s.md" % hid(80),
                        "Private & Shared/Old Tree/shot.png"):
                (export / rel).parent.mkdir(parents=True, exist_ok=True)
                (export / rel).write_text("x")
            out = Mirror(client, cfg, State(cfg.state_dir)).coverage(export)
            self.assertEqual(out["export_total"], 8)
            self.assertEqual(out["reachable"], 3)
            self.assertEqual(out["unreachable"], 5)
            self.assertEqual([(g[0], g[1]) for g in out["groups"]],
                             [("Private & Shared/Old Tree", 4), ("Teamspace/Sub", 1)])
            self.assertEqual(out["groups"][0][2][:2], ["Deep one", "Deep two"])
            self.assertEqual(out["new_since_export"], 3)  # P3 (database), P5, P6 exist in the walk, not in the export
            self.assertEqual(paths_of(lane), ["LANE.md"])


if __name__ == "__main__":
    unittest.main()


def with_credentials(client):
    """Add a credential subtree to the fixture: 7 Keys and Creds (under Root) > 8 GitHub PAT,
    and 9 Credentials Vault [db, ds 90] (under Root) > row 10 xAI key. Fetching the content
    of 7, 8 or 10 raises, so any leak of a fetch into an excluded subtree shows up as an error."""
    client.add_page(7, "Keys and Creds", client.under(1), body=[para(70, "ghp_secret")])
    client.add_page(8, "GitHub PAT", client.under(7), body=[para(80, "ghp_secret")])
    client.add_database(9, 90, "Credentials Vault", client.under(1), SCHEMA)
    client.add_row(10, 9, 90, "xAI key", {"Status": {"type": "select", "select": None}}, body=[para(100, "xai-secret")])
    client.fail_children_for.update({hid(7), hid(8), hid(10)})


M7 = "Private & Shared/Root/Keys and Creds %s.md" % hid(7)
M9 = "Private & Shared/Root/Credentials Vault %s.md" % hid(9)
P8 = "Private & Shared/Root/Keys and Creds/GitHub PAT %s.md" % hid(8)
C9 = "Private & Shared/Root/Credentials Vault %s_all.csv" % hid(9)
P10 = "Private & Shared/Root/Credentials Vault/xAI key %s.md" % hid(10)


class Excludes(unittest.TestCase):
    def test_full_writes_markers_and_never_fetches_under_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            with_credentials(client)
            queries_before = client.queries
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.excluded, 2)
            self.assertIn(M7, paths_of(lane))
            self.assertIn(M9, paths_of(lane))
            for gone in (P8, C9, P10):
                self.assertNotIn(gone, paths_of(lane))
            marker = (lane / M7).read_text()
            self.assertEqual(marker.count("\n"), 1)
            self.assertIn('title matched "creds"', marker)
            self.assertIn("credentials", (lane / M9).read_text())
            self.assertEqual(client.queries, queries_before + 1)  # LW Songs only
            self.assertIn(", excluded 2", rep.summary())
            self.assertEqual(sorted(rep.excluded_paths), sorted([M7, M9]))
            status = (cfg.state_dir / "last-status").read_text()
            self.assertTrue(status.startswith("OK "), status)

    def test_dry_run_lists_the_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            with_credentials(client)
            rep = Mirror(client, cfg, State(cfg.state_dir)).full(dry_run=True)
            self.assertEqual(sorted(rep.excluded_paths), sorted([M7, M9]))
            self.assertIn(M7, rep.would_write)
            self.assertEqual(paths_of(lane), ["LANE.md"])

    def test_previously_mirrored_subtree_is_replaced_by_the_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, exclude_titles=[])
            with_credentials(client)
            client.fail_children_for.clear()
            Mirror(client, cfg, State(cfg.state_dir)).full()
            for present in (P8, C9, P10):
                self.assertIn(present, paths_of(lane))
            cfg.exclude_titles = ["creds", "credentials"]
            client.fail_children_for.update({hid(7), hid(8), hid(10)})
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            for gone in (P8, C9, P10):
                self.assertNotIn(gone, paths_of(lane))
            self.assertFalse((lane / "Private & Shared/Root/Keys and Creds").exists())
            self.assertFalse((lane / "Private & Shared/Root/Credentials Vault").exists())
            self.assertIn(M7, paths_of(lane))
            self.assertIn(M9, paths_of(lane))
            self.assertEqual(rep.moved, 0)
            self.assertGreaterEqual(rep.deleted, 3)
            manifest = Mirror(client, cfg, State(cfg.state_dir)).manifest.items
            self.assertNotIn(hid(8), manifest)
            self.assertNotIn(hid(10), manifest)
            self.assertEqual(manifest[hid(9)]["excluded"], 'title matched "credentials"')

    def test_dropping_the_rule_restores_the_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            with_credentials(client)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            cfg.exclude_titles = []
            client.fail_children_for.clear()
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertNotIn(M9, paths_of(lane))
            for present in (P8, C9, P10):
                self.assertIn(present, paths_of(lane))

    def test_id_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, exclude_titles=[], exclude_ids={hid(2)})
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertIn("NOTION_EXCLUDE_IDS", (lane / P2).read_text())
            self.assertEqual(paths_of(lane), ["LANE.md", P1, P2])

    def test_delta_marks_a_new_credentials_page_and_drops_its_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            client.add_page(12, "Creds", client.under(2), edited=LATER, body=[para(120, "sk-secret")])
            client.add_page(13, "Token", client.under(12), edited=LATER, body=[para(130, "sk-secret")])
            client.fail_children_for.update({hid(12), hid(13)})
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            m12 = "Private & Shared/Root/Music/Creds %s.md" % hid(12)
            self.assertIn(m12, paths_of(lane))
            self.assertFalse(any("Token" in p for p in paths_of(lane)))
            self.assertEqual(rep.excluded_paths, [m12])
            self.assertEqual(State(cfg.state_dir).read_cursor(), LATER)

    def test_delta_removes_a_page_moved_under_an_excluded_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            with_credentials(client)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertIn(P6, paths_of(lane))
            client.pages[hid(6)]["parent"] = client.under(7)
            client.pages[hid(6)]["last_edited_time"] = LATER
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            self.assertNotIn(P6, paths_of(lane))
            self.assertFalse(any("Lyrics" in p for p in paths_of(lane)))
            self.assertNotIn(hid(6), Mirror(client, cfg, State(cfg.state_dir)).manifest.items)

    def test_check_and_coverage_count_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            with_credentials(client)
            mirror = Mirror(client, cfg, State(cfg.state_dir))
            self.assertEqual(mirror.check()["excluded"], 2)
            export = Path(tmp) / "export"
            for rel in (P1, P8, C9, P10):
                (export / rel).parent.mkdir(parents=True, exist_ok=True)
                (export / rel).write_text("x")
            cov = mirror.coverage(export)
            self.assertEqual(cov["excluded"], 3)
            self.assertEqual(cov["unreachable"], 0)


SCANNER = """#!/bin/sh
# flags every listed file whose content holds the word HUNTER2
hits=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  if grep -q HUNTER2 -- "$f"; then echo "--- $f"; hits=$((hits+1)); fi
done < "$1"
echo "files with hits: $hits"
[ "$hits" -eq 0 ]
"""


def scanner(tmp):
    path = Path(tmp) / "scan.sh"
    path.write_text(SCANNER)
    path.chmod(0o755)
    return str(path)


class SecretScan(unittest.TestCase):
    def test_clean_run_scans_and_stays_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, secret_scan=scanner(tmp))
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.secrets, [])
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("OK "))
            self.assertTrue((cfg.state_dir / "secret-scan.log").exists())
            listed = (cfg.state_dir / "secret-scan.list").read_text().splitlines()
            self.assertIn("raw/tools/Notion/" + P2, listed)
            self.assertIn("raw/tools/Notion/" + IMG, listed)

    def test_a_secret_in_a_page_fails_the_status_but_advances_the_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, secret_scan=scanner(tmp))
            client.blocks[hid(6)] = [para(60, "password is HUNTER2")]
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.secrets, ["raw/tools/Notion/" + P6])
            status = (cfg.state_dir / "last-status").read_text()
            self.assertTrue(status.startswith("FAILED "), status)
            self.assertIn("SECRETS flagged in 1 file(s)", status)
            self.assertIn(P6, status)
            self.assertFalse((cfg.state_dir / "last-success").exists())
            self.assertEqual(State(cfg.state_dir).read_cursor(), EDIT)
            self.assertIsNotNone(State(cfg.state_dir).read_last_full())
            self.assertIn("SECRETS flagged", rep.summary())

    def test_full_scans_the_whole_lane_delta_only_what_it_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, secret_scan=scanner(tmp))
            Mirror(client, cfg, State(cfg.state_dir)).full()
            stray = lane / "Private & Shared" / "legacy note.md"
            stray.write_text("HUNTER2 left behind by an old export\n")
            client.retitle(2, "Music!", LATER)
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.secrets, [])
            listed = (cfg.state_dir / "secret-scan.list").read_text().splitlines()
            self.assertNotIn("raw/tools/Notion/Private & Shared/legacy note.md", listed)
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.secrets, ["raw/tools/Notion/Private & Shared/legacy note.md"])

    def test_scanner_that_cannot_run_is_an_error_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, secret_scan=str(Path(tmp) / "missing.sh"))
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(len(rep.errors), 1)
            self.assertIn("secret scan could not run", rep.errors[0])
            self.assertTrue((cfg.state_dir / "last-status").read_text().startswith("FAILED "))
            self.assertIsNone(State(cfg.state_dir).read_cursor())

    def test_no_scanner_configured_means_no_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp, secret_scan="")
            client.blocks[hid(6)] = [para(60, "HUNTER2")]
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.secrets, [])
            self.assertFalse((cfg.state_dir / "secret-scan.log").exists())


class ExcludedRow(unittest.TestCase):
    def test_excluded_row_gets_a_marker_and_leaves_the_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, client, lane = workspace(tmp)
            Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertIn("Alive", (lane / P3).read_text())
            client.retitle(4, "API keys", LATER)
            client.blocks[hid(4)] = [para(40, "sk-secret")]
            client.fail_children_for.add(hid(4))
            rep = Mirror(client, cfg, State(cfg.state_dir)).delta()
            self.assertEqual(rep.errors, [])
            marker = "Private & Shared/Root/Music/LW Songs/API keys %s.md" % hid(4)
            self.assertIn(marker, paths_of(lane))
            self.assertNotIn(P4, paths_of(lane))
            self.assertNotIn(P6, paths_of(lane))  # Lyrics sat under the row
            csv = (lane / P3).read_text()
            self.assertIn("Atlantic", csv)
            self.assertNotIn("API keys", csv)
            self.assertNotIn("Alive", csv)
            rep = Mirror(client, cfg, State(cfg.state_dir)).full()
            self.assertEqual(rep.errors, [])
            self.assertNotIn("API keys", (lane / P3).read_text())
