#!/usr/bin/env python3
"""Register a trained YOLO model into RoadVisionAI (weights -> MinIO, row -> ai_models).

Usage (from anywhere, against a running stack):
    python3 scripts/register_model.py /path/to/best.pt \
        --name yolov11n-road-damage --version v1 \
        --api http://localhost:8000 --email admin@dgr.gov.ma --password 'Admin@2026!' \
        --map50 0.349 --epochs 50 --dataset roboflow-road-damage --dataset-size 4915 \
        --promote

Uses only the public API — no direct DB access required.
"""

import argparse
import json
import sys
import urllib.request


def api(base: str, path: str, *, token: str | None = None, data=None, files=None):
    import mimetypes
    import uuid as _uuid

    url = base.rstrip("/") + path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if files:
        boundary = _uuid.uuid4().hex
        body = b""
        for key, val in (data or {}).items():
            body += (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'
            ).encode()
        for key, (fname, blob) in files.items():
            ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            body += (
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; '
                    f'filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'
                ).encode()
                + blob
                + b"\r\n"
            )
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    elif data is not None:
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url, data=json.dumps(data).encode(), headers=headers, method="POST"
        )
    else:
        req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("weights", help="path to best.pt")
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--map50", type=float)
    ap.add_argument("--map50-95", type=float, dest="map50_95")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--dataset")
    ap.add_argument("--dataset-size", type=int, dest="dataset_size")
    ap.add_argument("--notes")
    ap.add_argument("--promote", action="store_true", help="promote to production after upload")
    args = ap.parse_args()

    with open(args.weights, "rb") as f:
        weights = f.read()
    print(f"Weights: {args.weights} ({len(weights) / 1e6:.1f} MB)")

    token = api(args.api, "/api/auth/login", data={"email": args.email, "password": args.password})[
        "access_token"
    ]

    metadata = {
        k: getattr(args, k)
        for k in ("map50", "map50_95", "epochs", "dataset_size", "notes")
        if getattr(args, k)
    }
    if args.dataset:
        metadata["dataset_name"] = args.dataset
    model = api(
        args.api,
        "/api/models",
        token=token,
        data={"name": args.name, "version": args.version, "metadata": json.dumps(metadata)},
        files={"weights": ("best.pt", weights)},
    )
    print(f"Registered: {model['id']} status={model['status']}")

    if args.promote:
        model = api(args.api, f"/api/models/{model['id']}/promote", token=token, data={})
        print(f"Promoted: is_active={model['is_active']} status={model['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
