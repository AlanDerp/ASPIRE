"""Final-frame bowl-vs-plate offset using a CIRCLE FIT of each object's rim band.
Both the bowl and the plate are circular, sit next to each other and share the camera, so a
circle fit cancels most of the viewing-geometry bias that a point-mean centroid carries.
Usage: python circle_fit_probe.py <dir_with_trial_dirs> [seed...]"""
import glob, os, sys, base64, json, io
import numpy as np
from PIL import Image
import urllib.request

SAM = "http://127.0.0.1:8114/segment"

def sam3(rgb, text, topn=10):
    buf = io.BytesIO(); Image.fromarray(rgb).save(buf, format="PNG")
    req = urllib.request.Request(SAM, data=json.dumps(
        {"image_base64": base64.b64encode(buf.getvalue()).decode(), "text_prompt": text}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["results"][:topn]

def world_pts(depth, K, E):
    h, w = depth.shape
    u, v = np.meshgrid(np.arange(w), np.arange(h))
    z = depth.reshape(-1); ok = z > 1e-6
    u = u.reshape(-1)[ok].astype(float); v = v.reshape(-1)[ok].astype(float); z = z[ok]
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    cam = np.stack([(u - cx) / fx * z, (v - cy) / fy * z, z], axis=1)
    E = np.asarray(E, float).reshape(4, 4)
    return cam @ E[:3, :3].T + E[:3, 3], ok.reshape(-1)

def fit_circle(x, y):
    A = np.stack([x, y, np.ones_like(x)], axis=1)
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    r = np.sqrt(sol[2] + cx * cx + cy * cy)
    return np.array([cx, cy]), float(r)

def rim_cloud(P, q=0.88, ransac=400, tol=0.004):
    """rim = the top part of the object; fit a circle robustly (RANSAC-lite)."""
    z = P[:, 2]
    R = P[z >= np.percentile(z, q * 100)]
    best, bestn = None, 0
    rng = np.random.default_rng(0)
    if len(R) < 20:
        return None
    for _ in range(ransac):
        idx = rng.choice(len(R), 3, replace=False)
        try:
            c, r = fit_circle(R[idx, 0], R[idx, 1])
        except Exception:
            continue
        if not (0.02 < r < 0.16):
            continue
        d = np.abs(np.hypot(R[:, 0] - c[0], R[:, 1] - c[1]) - r)
        n = int((d < tol).sum())
        if n > bestn:
            bestn, best = n, (c, r)
    if best is None:
        return None
    c, r = best
    inl = np.abs(np.hypot(R[:, 0] - c[0], R[:, 1] - c[1]) - r) < tol
    c2, r2 = fit_circle(R[inl, 0], R[inl, 1])
    return c2, r2, int(inl.sum())

def blobs(rgb, dep, K, E, text, minpts=250):
    pts, ok = world_pts(dep, K, E)
    out = []
    for r in sam3(rgb, text):
        if r.get("score", 0) < 0.02: continue
        m = np.frombuffer(base64.b64decode(r["mask_base64"]), np.uint8).reshape(tuple(r["shape"])) > 0
        P = pts[m.reshape(-1)[ok]]
        if len(P) < minpts: continue
        out.append((float(r["score"]), P))
    return out

D = sys.argv[1]
SPEC = sys.argv[2:]
if not SPEC:
    SPEC = ["%d:" % s for s in range(51, 66)]
for spec in SPEC:
    s, _, want = spec.partition(":")
    s = int(s)
    hits = glob.glob(D + "/trial_%d_*" % s)
    if not hits:
        print("seed %-3d : no run dir" % s); continue
    tag = os.path.basename(hits[0]); rew = "1" if "reward_1" in tag else "0"
    K_dir = hits[0] + "/keyframes"
    steps = sorted({int(os.path.basename(p).split("_")[1])
                    for p in glob.glob(K_dir + "/step_*_obs_agentview.jpg")})
    st = int(want) if want else steps[-1]
    rgb = np.array(Image.open("%s/step_%03d_obs_agentview.jpg" % (K_dir, st)).convert("RGB"))
    dep = np.load("%s/step_%03d_depth_agentview.npy" % (K_dir, st))
    if dep.ndim == 3: dep = dep[:, :, 0]
    K = np.asarray(np.load("%s/step_%03d_intrinsics_agentview.npy" % (K_dir, st)), float).reshape(3, 3)
    E = np.load("%s/step_%03d_extrinsics_agentview.npy" % (K_dir, st))
    print("=== seed %d r=%s step=%03d" % (s, rew, st), flush=True)
    for text, tag2 in (("bowl", "BOWL"), ("plate", "PLATE")):
        for sc, P in blobs(rgb, dep, K, E, text)[:4]:
            c = P.mean(axis=0); z = P[:, 2]
            bb = np.array([(P[:, 0].max() + P[:, 0].min()) / 2,
                           (P[:, 1].max() + P[:, 1].min()) / 2])
            f = rim_cloud(P)
            extra = ("  circle=(%.3f,%.3f) r=%.3f inl=%d" % (f[0][0], f[0][1], f[1], f[2])) if f else "  circle=none"
            print("  %-5s s=%.2f n=%4d mean=(%.3f,%.3f) bbox=(%.3f,%.3f) z=[%.4f..%.4f]%s"
                  % (tag2, sc, len(P), c[0], c[1], bb[0], bb[1], np.percentile(z, 2),
                     np.percentile(z, 98), extra), flush=True)
