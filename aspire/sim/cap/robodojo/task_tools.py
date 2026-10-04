"""Public RGBD helpers for the explicitly configured RoboDojo pinhole camera.

Only valid for camera.mesh=pinhole and its identity local USD transform, as
verified in the public sensor configuration. No asset geometry or task internals.
"""
import numpy as np
from aspire.sim.cap.robodojo.tools import RoboDojoTools


class TaskTools(RoboDojoTools):
    def functions(self):
        return {**super().functions(), "localize_objects": self.localize_objects,
                "move_ee": self.move_ee, "wait_frames": self.wait_frames}

    def localize_objects(self, text, camera="cam_head", min_score=.5):
        """Return SAM3 detections with world points computed from public RGBD.

        Each result has point (XYZ median visible surface, meters), mask, box,
        score and label. Empty results mean no valid detection, never a default
        origin. Raw SAM3 queries below min_score are excluded; overlapping masks
        are deduplicated (IoU > 0.7). Points are visible surfaces, not object centers or TCPs.
        The explicit USD pinhole calibration flips optical Y/Z into mount axes.
        """
        obs = self.get_observation()
        cam = obs["cameras"][camera]
        depth = cam["images"]["depth"].squeeze(-1)
        k, t = cam["intrinsics"], cam["pose_mat"]
        optical_to_world = t @ np.diag([1., -1., -1., 1.])
        if not 0 <= float(min_score) <= 1:
            raise ValueError("min_score must be between zero and one")
        results = []
        accepted_masks = []
        candidates = sorted(self.segment_sam3_text_prompt(cam["images"]["rgb"], text),
                            key=lambda d: float(d["score"]), reverse=True)
        for detection in candidates:
            if float(detection["score"]) < min_score:
                continue
            mask = np.asarray(detection["mask"], dtype=bool)
            if any(np.count_nonzero(mask & old) / max(1, np.count_nonzero(mask | old)) > .7
                   for old in accepted_masks):
                continue
            valid = detection["mask"] & np.isfinite(depth) & (depth > 0) & (depth < 5)
            ys, xs = np.nonzero(valid)
            if len(xs) < 8:
                continue
            z = depth[ys, xs]
            xyz = np.column_stack(((xs-k[0,2])*z/k[0,0], (ys-k[1,2])*z/k[1,1], z))
            world = xyz @ optical_to_world[:3,:3].T + optical_to_world[:3,3]
            results.append({**detection, "point": np.median(world, axis=0)})
            accepted_masks.append(mask)
        return results

    def move_ee(self, position, quaternion=None, arm="left", max_frames=100, tolerance=.015):
        """Move with feedback in <=2cm XYZ increments; preserve measured rotation by default.

        Absolute world XYZ meters; explicit WXYZ quaternion if supplied. Stops
        when measured XYZ is within tolerance; raises if target is not reached
        within max_frames. Does not verify a grasp, collision or task completion.
        Use approach/retreat waypoints and inspect images after manipulation.
        """
        target = np.asarray(position, dtype=float)
        if target.shape != (3,) or not np.isfinite(target).all():
            raise ValueError("position must be finite XYZ")
        if not 1 <= int(max_frames) <= 200 or not .001 <= float(tolerance) <= .05:
            raise ValueError("invalid feedback motion budget")
        for _ in range(int(max_frames)):
            state = self.get_observation()["robot_state"][arm+"_ee_pose"]
            delta = target-state[:3]
            distance = np.linalg.norm(delta)
            if distance <= tolerance:
                return
            next_xyz = state[:3]+delta*min(1., .02/distance)
            self.goto_pose(next_xyz, state[3:] if quaternion is None else quaternion, arm=arm)
        measured = self.get_observation()["robot_state"][arm+"_ee_pose"][:3]
        if np.linalg.norm(target-measured) <= tolerance:
            return
        raise RuntimeError("EE target not reached within feedback budget")

    def wait_frames(self, frames=10):
        """Hold measured poses and grippers for bounded fresh-feedback frames."""
        if not 1 <= int(frames) <= 100:
            raise ValueError("frames must be between 1 and 100")
        for _ in range(int(frames)):
            self.bridge.send(self.spec.hold_action(self.bridge.observe()["state"]))
