#!/usr/bin/env python3
"""Block the shell commands and fetches an agent most often gets wrong, judged by parsed structure.

A PreToolUse guard for the Bash and WebFetch tools, with a direct mode for tests and manual use. It
tokenizes a command with the standard shell lexer, splits it into simple commands at pipes and list
operators, finds the word in command position, and judges five classes:

- credential read: a command that names a key directory, a credential file, a password store, the
  keychain, or a decryption of one of them
- credential write: a redirection, copy, move, tee, or in-place edit aimed at an environment file,
  a credentials file, a key directory, or the repository's own configuration, or a change to the
  repository's remotes
- dangerous command: a recursive delete, a fork bomb, a download piped into a shell, a decoded
  payload piped into an interpreter, or a raw write to a device
- masked push: a git push whose exit status a pipe would replace with the last stage's
- private address: a fetch of a loopback, private, link-local, or local-name host

It sees top-level structure only. A command hidden inside a command substitution, a string handed to
an interpreter, or a script invoked by path is not seen; the project's own gates remain the boundary
for those. A command the lexer cannot parse is blocked rather than guessed at. It prevents an
agent's mistakes; it is not a defense against a hostile one.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

PIPES = {"|", "|&"}
LIST_OPERATORS = {"||", "&&", ";", "&", "(", ")"}
OUTPUT_REDIRECTIONS = {">", ">>", ">|", "&>", "&>>"}
INPUT_REDIRECTIONS = {"<", "<<", "<<<"}
DESCRIPTOR_REDIRECTIONS = {">&", "<&"}
WRAPPERS = {"sudo", "doas", "env", "nohup", "time", "exec", "command", "nice", "caffeinate"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = SHELLS | {"python", "python3", "perl", "ruby", "node", "eval", "source", "."}
DOWNLOADERS = {"curl", "wget", "fetch"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
CREDENTIAL_READ_PATHS = (
    re.compile(r"(?:^|/)\.ssh(?:/|$)"),
    re.compile(r"(?:^|/)\.aws/credentials$"),
    re.compile(r"(?:^|/)\.gnupg(?:/|$)"),
    re.compile(r"^/etc/shadow$"),
    re.compile(r"(?:^|/)\.netrc$"),
    re.compile(r"(?:^|/)\.password-store(?:/|$)"),
)
KEYCHAIN_SUBCOMMANDS = {
    "dump-keychain",
    "find-generic-password",
    "find-internet-password",
    "find-key",
    "export",
}
CREDENTIAL_WRITE_PATHS = (
    re.compile(r"(?:^|/)\.env(?:\.[A-Za-z0-9_.-]+)?$"),
    re.compile(r"(?:^|/)credentials\.json$"),
    re.compile(r"(?:^|/)\.ssh(?:/|$)"),
    re.compile(r"(?:^|/)\.git/config$"),
)
DEVICE_PATH = re.compile(r"^/dev/(?:disk|rdisk|sd|nvme|hd|mmcblk)")
LOCAL_NAME_SUFFIXES = (".local", ".localhost", ".internal")


class GuardError(ValueError):
    """The input could not be judged, so it is not admitted."""


@dataclass
class Simple:
    """One simple command: its words, redirection targets, and the operator that follows it."""

    words: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    operator: str | None = None

    def command(self) -> tuple[str | None, list[str]]:
        """The word in command position, looked up through wrappers and assignments."""
        index = 0
        while index < len(self.words):
            word = self.words[index]
            if ASSIGNMENT.fullmatch(word):
                index += 1
                continue
            name = word.rsplit("/", 1)[-1]
            if name in WRAPPERS:
                index += 1
                while index < len(self.words) and self.words[index].startswith("-"):
                    index += 1
                continue
            return name, self.words[index + 1 :]
        return None, []


def parse(command: str) -> list[Simple]:
    """Split a command line into simple commands, keeping redirections and list operators."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise GuardError(f"could not parse the command: {exc}") from exc
    simples: list[Simple] = []
    current = Simple()
    pending: str | None = None
    for token in tokens:
        if pending is not None:
            if pending == "output":
                current.outputs.append(token)
            elif pending == "input":
                current.inputs.append(token)
            pending = None
            continue
        if token in OUTPUT_REDIRECTIONS:
            pending = "output"
        elif token in INPUT_REDIRECTIONS:
            pending = "input"
        elif token in DESCRIPTOR_REDIRECTIONS:
            pending = "descriptor"
        elif token in PIPES or token in LIST_OPERATORS:
            current.operator = token
            simples.append(current)
            current = Simple()
        else:
            current.words.append(token)
    if pending in {"output", "input"}:
        raise GuardError("a redirection has no target")
    if current.words or current.outputs or current.inputs:
        simples.append(current)
    return simples


def _matches(value: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def _positional(arguments: Sequence[str]) -> list[str]:
    return [argument for argument in arguments if not argument.startswith("-")]


def _credential_read(simple: Simple) -> str | None:
    name, arguments = simple.command()
    for value in [*simple.words, *simple.inputs]:
        if _matches(value, CREDENTIAL_READ_PATHS):
            return f"{value} is a key or credential path"
    positional = _positional(arguments)
    if name == "security" and positional and positional[0] in KEYCHAIN_SUBCOMMANDS:
        return f"security {positional[0]} reads the keychain"
    if name == "pass" and (not positional or positional[0] in {"show", "-c"} or "-c" in arguments):
        return "pass reveals a password-store entry"
    if name == "gpg" and any(argument in {"-d", "--decrypt"} for argument in arguments):
        return "gpg --decrypt reveals an encrypted secret"
    return None


def _credential_write(simple: Simple) -> str | None:
    name, arguments = simple.command()
    for target in simple.outputs:
        if _matches(target, CREDENTIAL_WRITE_PATHS):
            return f"redirection writes {target}"
    positional = _positional(arguments)
    if name == "tee":
        for target in positional:
            if _matches(target, CREDENTIAL_WRITE_PATHS):
                return f"tee writes {target}"
    if (
        name in {"cp", "mv", "install"}
        and positional
        and _matches(positional[-1], CREDENTIAL_WRITE_PATHS)
    ):
        return f"{name} writes {positional[-1]}"
    if name == "sed" and any(argument.startswith("-i") for argument in arguments):
        for target in positional:
            if _matches(target, CREDENTIAL_WRITE_PATHS):
                return f"sed -i edits {target}"
    if name == "git" and positional[:2] in (["remote", "add"], ["remote", "set-url"]):
        return "git remote changes where this repository publishes"
    return None


def _dangerous(simple: Simple, raw: str) -> str | None:
    name, arguments = simple.command()
    if name == "rm":
        flags = [argument for argument in arguments if argument.startswith("-")]
        if any(
            argument.startswith("--") and argument == "--recursive" for argument in flags
        ) or any(
            not argument.startswith("--") and ("r" in argument or "R" in argument)
            for argument in flags
        ):
            return "recursive delete; delete named files, or use find with -delete"
    if name in {"mkfs", "newfs"} or (name or "").startswith("mkfs."):
        return f"{name} creates a filesystem"
    if name == "dd" and any(
        argument.startswith("of=") and DEVICE_PATH.match(argument[3:]) for argument in arguments
    ):
        return "dd writes a raw device"
    if (
        name == "diskutil"
        and arguments
        and arguments[0].lower().startswith(("erase", "partition", "reformat", "zero"))
    ):
        return f"diskutil {arguments[0]} destroys a volume"
    for target in simple.outputs:
        if DEVICE_PATH.match(target):
            return f"redirection writes the raw device {target}"
    if name == "eval" and "base64" in raw:
        return "eval of a decoded payload"
    return None


def _pipeline_findings(simples: Sequence[Simple]) -> list[tuple[str, str]]:
    """Judge each pipeline as a whole: what feeds a shell, and what a pipe would hide."""
    findings: list[tuple[str, str]] = []
    pipeline: list[Simple] = []
    for simple in simples:
        pipeline.append(simple)
        if simple.operator in PIPES:
            continue
        names = [simple.command()[0] for simple in pipeline]
        for position, name in enumerate(names):
            earlier = names[:position]
            if name in SHELLS and any(previous in DOWNLOADERS for previous in earlier):
                findings.append(("dangerous command", "a download piped into a shell"))
            if name in INTERPRETERS and any(
                previous == "base64"
                and any(
                    argument in {"-d", "-D", "--decode"}
                    for argument in pipeline[index].command()[1]
                )
                for index, previous in enumerate(earlier)
            ):
                findings.append(
                    ("dangerous command", "a decoded payload piped into an interpreter")
                )
        for position, simple in enumerate(pipeline):
            name, arguments = simple.command()
            if (
                name == "git"
                and _positional(arguments)[:1] == ["push"]
                and position < len(pipeline) - 1
            ):
                findings.append(
                    (
                        "masked push",
                        "a pipeline reports the last stage's exit status, not the push's; run it alone",
                    )
                )
        pipeline = []
    return findings


def judge_command(command: str) -> list[tuple[str, str]]:
    """Every (class, reason) the command triggers; empty means admitted."""
    if FORK_BOMB.search(command):
        return [("dangerous command", "a fork bomb")]
    simples = parse(command)
    findings: list[tuple[str, str]] = []
    for simple in simples:
        for label, judge in (
            ("credential read", _credential_read),
            ("credential write", _credential_write),
        ):
            reason = judge(simple)
            if reason:
                findings.append((label, reason))
        reason = _dangerous(simple, command)
        if reason:
            findings.append(("dangerous command", reason))
    findings.extend(_pipeline_findings(simples))
    return findings


def judge_url(url: str) -> list[tuple[str, str]]:
    """A fetch is admitted only when its host is a public name or address."""
    try:
        name = urlsplit(url).hostname
    except ValueError as exc:
        raise GuardError(f"could not parse the URL: {exc}") from exc
    if not name:
        raise GuardError("the URL has no host")
    lowered = name.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(LOCAL_NAME_SUFFIXES):
        return [("private address", f"{name} is a local name")]
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return []
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
    ):
        return [("private address", f"{name} is not a public address")]
    return []


def _hook_payload() -> tuple[str, str]:
    """(kind, subject) from a PreToolUse payload: a Bash command or a WebFetch URL."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise GuardError(f"invalid hook JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GuardError("hook payload must be an object")
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("hook payload has no tool_input object")
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            raise GuardError("Bash payload has no command")
        return "command", command
    if tool_name == "WebFetch":
        url = tool_input.get("url")
        if not isinstance(url, str) or not url.strip():
            raise GuardError("WebFetch payload has no url")
        return "url", url
    return "other", str(tool_name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--command", help="Judge this shell command directly")
    subject.add_argument("--url", help="Judge this fetch URL directly")
    subject.add_argument(
        "--claude-hook",
        action="store_true",
        help="Read a Claude Code PreToolUse payload from stdin (Bash or WebFetch)",
    )
    subject.add_argument(
        "--codex-hook",
        action="store_true",
        help="Read a Codex PreToolUse payload from stdin (Bash)",
    )
    parser.add_argument("--json", action="store_true", help="Print the decision as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command is not None:
            kind, subject = "command", args.command
        elif args.url is not None:
            kind, subject = "url", args.url
        else:
            kind, subject = _hook_payload()
        if kind == "other":
            findings: list[tuple[str, str]] = []
            reason = f"{subject} is not a tool this guard judges"
        else:
            findings = judge_command(subject) if kind == "command" else judge_url(subject)
            reason = "; ".join(f"{label}: {detail}" for label, detail in findings) or "no finding"
    except GuardError as exc:
        print(f"command_guard: BLOCKED: {exc}", file=sys.stderr)
        return 2
    allowed = not findings
    if args.json:
        print(
            json.dumps(
                {
                    "decision": "allow" if allowed else "block",
                    "findings": [{"class": label, "reason": detail} for label, detail in findings],
                },
                sort_keys=True,
            )
        )
    elif allowed:
        print(f"ALLOWED: {reason}")
    else:
        print(f"BLOCKED: {reason}", file=sys.stderr)
    return 0 if allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
