import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "oes-raid-leds.py"
SPEC = importlib.util.spec_from_file_location("oes_raid_leds", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RaidStatusTests(unittest.TestCase):
    def build_controller(self, root: Path):
        md = root / "sys/block/md0/md"
        md.mkdir(parents=True)
        (md / "degraded").write_text("0\n", encoding="ascii")
        (md / "array_state").write_text("clean\n", encoding="ascii")
        (md / "raid_disks").write_text("3\n", encoding="ascii")
        for slot, member in enumerate(("sda1", "sdb1", "sdc1")):
            target = root / "members" / f"dev-{member}"
            target.mkdir(parents=True)
            (target / "state").write_text("in_sync\n", encoding="ascii")
            (md / f"rd{slot}").symlink_to(target, target_is_directory=True)
        leds = [root / f"led{slot}" for slot in range(3)]
        return MODULE.RaidLedController(
            md_sys=md,
            leds=leds,
            ata_triggers=["ata1", "ata2", "ata3"],
            green_power=root / "green-power",
            red_power=root / "red-power",
        )

    def test_clean_three_disk_raid_is_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory))
            healthy, state, members = controller.raid_status()
            self.assertTrue(healthy)
            self.assertEqual("clean", state)
            self.assertEqual(["sda1", "sdb1", "sdc1"], [name for name, _ in members])

    def test_degraded_raid_is_unhealthy(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory))
            (controller.md_sys / "degraded").write_text("1\n", encoding="ascii")
            healthy, _, _ = controller.raid_status()
            self.assertFalse(healthy)


if __name__ == "__main__":
    unittest.main()
