"""Parse `firebase hosting:channel:deploy --json` and render the PR comment.

FirebaseExtended/action-hosting-deploy requires a service-account JSON key and
does not read ambient Application Default Credentials. The preview workflow
deploys with firebase-tools instead, then posts this comment with GITHUB_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

COMMENT_MARKER = "<!-- insummery-firebase-hosting-preview -->"


class PreviewDeployError(Exception):
    """The channel deploy JSON did not contain a usable preview URL."""


def extract_json_objects(text: str) -> list[Any]:
    """Return every JSON object in `text`, in order."""
    decoder = json.JSONDecoder()
    found: list[Any] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index] != "{":
            index += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        found.append(obj)
        index = end
    return found


def parse_channel_deploy(stdout: str) -> dict[str, str]:
    """Return url, expire_time, and site from firebase-tools JSON output."""
    objects = extract_json_objects(stdout)
    if not objects:
        raise PreviewDeployError("firebase --json produced no JSON object")

    payload = objects[-1]
    if not isinstance(payload, dict):
        raise PreviewDeployError("firebase --json output was not an object")
    if payload.get("status") == "error":
        message = payload.get("error") or "firebase hosting channel deploy failed"
        raise PreviewDeployError(str(message))

    result = payload.get("result")
    sites: list[dict[str, Any]] = []
    if isinstance(result, dict):
        sites = [value for value in result.values() if isinstance(value, dict)]
    elif isinstance(result, list):
        sites = [value for value in result if isinstance(value, dict)]

    for site in sites:
        url = site.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            expire = site.get("expireTime") or site.get("expire_time") or ""
            name = site.get("site") or ""
            return {
                "url": url,
                "expire_time": str(expire),
                "site": str(name),
            }

    raise PreviewDeployError("firebase channel deploy JSON did not include an https url")


def success_comment(*, project: str, sha: str, url: str, expire_time: str) -> str:
    short_sha = sha[:7] if sha else ""
    expires = f"\n- Expires: {expire_time}" if expire_time else ""
    return (
        f"{COMMENT_MARKER}\n"
        f"Preview for `{project}` is ready.\n\n"
        f"- URL: {url}\n"
        f"- Commit: `{short_sha}`"
        f"{expires}\n"
    )


def failure_comment(*, run_url: str) -> str:
    return (
        f"{COMMENT_MARKER}\n"
        "Hosting preview failed.\n\n"
        f"Workflow run: {run_url}\n"
    )


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render")
    render.add_argument("json_path")
    render.add_argument("--project", required=True)
    render.add_argument("--sha", required=True)
    render.add_argument("--comment-out", required=True)
    render.add_argument("--url-out", required=True)

    failed = sub.add_parser("failure-comment")
    failed.add_argument("--run-url", required=True)
    failed.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "failure-comment":
        _write(args.out, failure_comment(run_url=args.run_url))
        return 0

    with open(args.json_path, encoding="utf-8") as handle:
        stdout = handle.read()
    try:
        parsed = parse_channel_deploy(stdout)
    except PreviewDeployError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _write(args.url_out, parsed["url"])
    _write(
        args.comment_out,
        success_comment(
            project=args.project,
            sha=args.sha,
            url=parsed["url"],
            expire_time=parsed["expire_time"],
        ),
    )
    print(parsed["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
